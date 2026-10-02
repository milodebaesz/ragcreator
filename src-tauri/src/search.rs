//! Finding the recommendations that answer a question.
//!
//! The "Vraag" screen deliberately searches recommendations and Q&A pairs
//! only — never the guideline prose or the PDF. What comes out of here is also
//! all the language model gets to see, so a source that is not ranked here can
//! never end up in an answer.
//!
//! Ranking is BM25 over recommendations and Q&A pairs together, with each Q&A
//! pair counting towards the recommendation it was generated from. That is what
//! lets a Dutch question reach an English recommendation: the Dutch Q&A
//! variant matches the words, the recommendation inherits the score.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use tauri::State;

use crate::commands::{project_names, read_chunks_file, AppState, Chunk};

/// Words that say nothing about the subject, in both languages the questions
/// and the guidelines come in.
const STOPWORDS: &[&str] = &[
    // Dutch
    "de", "het", "een", "en", "of", "van", "in", "op", "met", "voor", "bij", "te", "aan",
    "als", "dat", "die", "dit", "om", "naar", "er", "is", "zijn", "wordt", "worden", "kan",
    "kunnen", "moet", "moeten", "wat", "welke", "wanneer", "hoe", "waarom", "wie", "ook",
    "niet", "geen", "door", "over", "tot", "uit", "dan", "nog", "heeft", "hebben", "je",
    "ik", "we", "mijn", "patient", "patiënt", "patienten", "patiënten",
    // English
    "the", "an", "and", "or", "for", "with", "to", "on", "at", "by", "be", "are", "was",
    "were", "should", "may", "can", "what", "which", "when", "how", "why", "who", "not",
    "no", "from", "as", "that", "this", "these", "those", "it", "its", "is", "in", "of",
    "patients", "patient", "recommended", "considered", "indicated",
];

/// Truncating long words is a crude stemmer, but it works for both languages
/// at once: statin/statins/statine, anticoagulation/anticoagulant.
const STEM_LEN: usize = 6;

fn terms(text: &str) -> Vec<String> {
    text.to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|w| w.chars().count() >= 2 && !STOPWORDS.contains(w))
        .map(|w| w.chars().take(STEM_LEN).collect())
        .collect()
}

/// A Q&A pair as the pipeline writes it. `chunk_id` sits at the top level in
/// current files and under `metadata` in older ones.
#[derive(Deserialize)]
struct QaRecord {
    #[serde(default)]
    question: String,
    #[serde(default)]
    answer: String,
    #[serde(default)]
    chunk_id: Option<String>,
    #[serde(default)]
    lang: Option<String>,
    #[serde(default)]
    metadata: Option<serde_json::Value>,
}

impl QaRecord {
    fn chunk_id(&self) -> Option<&str> {
        self.chunk_id.as_deref().or_else(|| {
            self.metadata
                .as_ref()
                .and_then(|m| m.get("chunk_id"))
                .and_then(|v| v.as_str())
        })
    }
}

/// Q&A pairs reference the normalised id ("esc-hf_2026_rec_1"), chunks carry
/// the raw one ("rec_1").
fn qa_belongs_to(qa_chunk_id: &str, chunk_id: &str) -> bool {
    qa_chunk_id == chunk_id
        || qa_chunk_id
            .strip_suffix(chunk_id)
            .map_or(false, |prefix| prefix.ends_with('_'))
}

#[derive(Serialize, Clone, Debug)]
pub struct QaSnippet {
    pub question: String,
    pub answer: String,
    pub lang: Option<String>,
}

#[derive(Serialize, Debug)]
pub struct AskHit {
    pub project: String,
    pub chunk: Chunk,
    pub score: f64,
    /// The Q&A pair of this recommendation that matched best, if any did.
    pub qa: Option<QaSnippet>,
}

/// One guideline's searchable material.
pub struct Corpus {
    pub project: String,
    pub chunks: Vec<Chunk>,
    qa: Vec<QaRecord>,
}

enum DocRef {
    Chunk(usize, usize),
    Qa(usize, usize),
}

/// How much a matching Q&A pair adds to its recommendation's own score. Below
/// one: the recommendation text is the source, the pair a paraphrase of it.
const QA_WEIGHT: f64 = 0.8;

pub fn rank(corpora: &[Corpus], query: &str, limit: usize) -> Vec<AskHit> {
    let query_terms: Vec<String> = {
        let mut t = terms(query);
        t.sort();
        t.dedup();
        t
    };
    if query_terms.is_empty() {
        return vec![];
    }

    // Every recommendation and every Q&A pair is a document of its own.
    let mut docs: Vec<(DocRef, Vec<String>)> = vec![];
    for (ci, corpus) in corpora.iter().enumerate() {
        for (i, c) in corpus.chunks.iter().enumerate() {
            let m = &c.metadata;
            let text = [
                c.text.as_str(),
                m.section.as_deref().unwrap_or(""),
                m.table_title.as_deref().unwrap_or(""),
                m.disease.as_deref().unwrap_or(""),
            ]
            .join(" ");
            docs.push((DocRef::Chunk(ci, i), terms(&text)));
        }
        for (i, q) in corpus.qa.iter().enumerate() {
            docs.push((DocRef::Qa(ci, i), terms(&format!("{} {}", q.question, q.answer))));
        }
    }
    if docs.is_empty() {
        return vec![];
    }

    let n = docs.len() as f64;
    let avg_len = docs.iter().map(|(_, t)| t.len()).sum::<usize>() as f64 / n;
    let idf: HashMap<&str, f64> = query_terms
        .iter()
        .map(|q| {
            let df = docs.iter().filter(|(_, t)| t.contains(q)).count() as f64;
            (q.as_str(), ((n - df + 0.5) / (df + 0.5) + 1.0).ln())
        })
        .collect();

    let bm25 = |doc_terms: &[String]| -> f64 {
        const K1: f64 = 1.2;
        const B: f64 = 0.75;
        let len = doc_terms.len() as f64;
        query_terms
            .iter()
            .map(|q| {
                let tf = doc_terms.iter().filter(|t| *t == q).count() as f64;
                if tf == 0.0 {
                    return 0.0;
                }
                idf[q.as_str()] * tf * (K1 + 1.0) / (tf + K1 * (1.0 - B + B * len / avg_len))
            })
            .sum()
    };

    // (corpus, chunk) → (own score, best Q&A score, best Q&A index)
    let mut scores: HashMap<(usize, usize), (f64, f64, Option<usize>)> = HashMap::new();
    for (doc, doc_terms) in &docs {
        let s = bm25(doc_terms);
        if s <= 0.0 {
            continue;
        }
        match *doc {
            DocRef::Chunk(ci, i) => scores.entry((ci, i)).or_insert((0.0, 0.0, None)).0 = s,
            DocRef::Qa(ci, qi) => {
                let corpus = &corpora[ci];
                let Some(qa_chunk) = corpus.qa[qi].chunk_id() else {
                    continue;
                };
                let Some(i) = corpus.chunks.iter().position(|c| qa_belongs_to(qa_chunk, &c.id))
                else {
                    continue;
                };
                let entry = scores.entry((ci, i)).or_insert((0.0, 0.0, None));
                if s > entry.1 {
                    entry.1 = s;
                    entry.2 = Some(qi);
                }
            }
        }
    }

    let mut ranked: Vec<((usize, usize), f64, Option<usize>)> = scores
        .into_iter()
        .map(|(key, (own, qa, qi))| (key, own + QA_WEIGHT * qa, qi))
        .collect();
    // Ties broken by position so the order is stable between runs.
    ranked.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    ranked.truncate(limit);

    ranked
        .into_iter()
        .map(|((ci, i), score, qi)| {
            let corpus = &corpora[ci];
            AskHit {
                project: corpus.project.clone(),
                chunk: corpus.chunks[i].clone(),
                score: (score * 100.0).round() / 100.0,
                qa: qi.map(|qi| {
                    let q = &corpus.qa[qi];
                    QaSnippet {
                        question: q.question.clone(),
                        answer: q.answer.clone(),
                        lang: q.lang.clone(),
                    }
                }),
            }
        })
        .collect()
}

fn load_corpus(state: &AppState, project: &str) -> Corpus {
    let chunks = read_chunks_file(state, project).unwrap_or_default();
    let qa = crate::commands::read_project_json::<Vec<QaRecord>>(state, project, "qa_pairs.json")
        .unwrap_or_default();
    Corpus { project: project.to_string(), chunks, qa }
}

/// A corpus straight from a project folder, for evaluating ranking against
/// data outside the app's own root.
#[cfg(test)]
fn corpus_from_dir(dir: &std::path::Path) -> Corpus {
    let read = |name: &str| std::fs::read_to_string(dir.join(name)).unwrap_or_default();
    Corpus {
        project: dir.file_name().unwrap().to_string_lossy().into_owned(),
        chunks: serde_json::from_str(&read("rag_chunks.json")).unwrap_or_default(),
        qa: serde_json::from_str(&read("qa_pairs.json")).unwrap_or_default(),
    }
}

/// Rank recommendations for a question, across every guideline or just one.
///
/// `keywords` are extra search terms — on iOS the language model's English
/// rendering of a Dutch question — searched together with the question itself.
#[tauri::command]
pub fn ask_search(
    state: State<AppState>,
    query: String,
    keywords: Option<Vec<String>>,
    project: Option<String>,
    limit: Option<usize>,
) -> Result<Vec<AskHit>, String> {
    let projects = match project {
        Some(p) => vec![p],
        None => project_names(&state)?,
    };
    let corpora: Vec<Corpus> = projects.iter().map(|p| load_corpus(&state, p)).collect();
    let full_query = format!("{} {}", query, keywords.unwrap_or_default().join(" "));
    Ok(rank(&corpora, &full_query, limit.unwrap_or(8).min(30)))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chunk(id: &str, text: &str) -> Chunk {
        serde_json::from_value(serde_json::json!({
            "id": id,
            "text": text,
            "metadata": { "type": "recommendation", "class": "Class I", "evidence": "A" }
        }))
        .unwrap()
    }

    fn qa(chunk_id: &str, question: &str) -> QaRecord {
        QaRecord {
            question: question.into(),
            answer: String::new(),
            chunk_id: Some(chunk_id.into()),
            lang: Some("nl".into()),
            metadata: None,
        }
    }

    fn corpus() -> Corpus {
        Corpus {
            project: "ESC HF".into(),
            chunks: vec![
                chunk("rec_1", "Treatment with a statin should be considered to reduce the risk of HF."),
                chunk("rec_2", "SGLT2 inhibitors are recommended in patients with HFrEF."),
                chunk("rec_11", "Exercise training is recommended to improve exercise capacity."),
            ],
            qa: vec![qa("esc-hf_2026_rec_2", "Welke medicatie verlaagt ziekenhuisopnames bij hartfalen met verminderde ejectiefractie?")],
        }
    }

    #[test]
    fn the_matching_recommendation_ranks_first() {
        let hits = rank(&[corpus()], "statins", 5);
        assert_eq!(hits[0].chunk.id, "rec_1");
    }

    /// The Dutch question shares no words with the English recommendation;
    /// only its Q&A pair connects them.
    #[test]
    fn a_dutch_question_reaches_an_english_recommendation_through_its_qa_pair() {
        let hits = rank(&[corpus()], "Welke medicatie bij verminderde ejectiefractie?", 5);
        assert_eq!(hits[0].chunk.id, "rec_2");
        assert!(hits[0].qa.is_some());
    }

    #[test]
    fn qa_ids_match_their_own_chunk_only() {
        assert!(qa_belongs_to("esc-hf_2026_rec_1", "rec_1"));
        assert!(qa_belongs_to("rec_1", "rec_1"));
        // "rec_11" ends with "rec_1"'s digits but is another recommendation.
        assert!(!qa_belongs_to("esc-hf_2026_rec_11", "rec_1"));
        assert!(!qa_belongs_to("esc-hf_2026_xrec_1", "rec_1"));
    }

    #[test]
    fn stopwords_alone_find_nothing() {
        assert!(rank(&[corpus()], "wat is de", 5).is_empty());
    }

    /// Runs against the guidelines on this machine, when there are any.
    /// `RAG_SEARCH_PROJECTS=<dir with project folders>` points it elsewhere.
    #[test]
    fn real_corpora_answer_a_dutch_question() {
        let corpora: Vec<Corpus> = match std::env::var_os("RAG_SEARCH_PROJECTS") {
            Some(dir) => std::fs::read_dir(dir)
                .map(|e| e.flatten().filter(|e| e.path().is_dir()).map(|e| corpus_from_dir(&e.path())).collect())
                .unwrap_or_default(),
            None => {
                let state = AppState;
                let Ok(projects) = project_names(&state) else { return };
                projects.iter().map(|p| load_corpus(&state, p)).collect()
            }
        };
        let query = std::env::var("RAG_SEARCH_QUERY")
            .unwrap_or_else(|_| "Wanneer moet een statine overwogen worden bij hartfalen?".into());
        if corpora.iter().all(|c| c.chunks.is_empty()) {
            return;
        }
        println!("{} recommendations, {} Q&A pairs",
            corpora.iter().map(|c| c.chunks.len()).sum::<usize>(),
            corpora.iter().map(|c| c.qa.len()).sum::<usize>());
        let hits = rank(&corpora, &query, 6);
        for h in &hits {
            println!("{:.2} [{}] {} — {}", h.score, h.project, h.chunk.id, &h.chunk.text[..h.chunk.text.len().min(90)]);
        }
        assert!(!hits.is_empty());
    }
}
