import Foundation

/// Finding the recommendations that answer a question.
///
/// Port of src-tauri/src/search.rs. Deliberately searches recommendations and
/// Q&A pairs only — never the guideline prose or the PDF — and what comes out
/// is all the language model gets to see.
///
/// BM25 over recommendations and Q&A pairs together, each Q&A pair counting
/// towards the recommendation it was generated from. That lets a Dutch question
/// reach an English recommendation: the Dutch Q&A variant matches the words,
/// the recommendation inherits the score.
enum AskSearch {
    struct Corpus {
        let project: String
        let chunks: [Chunk]
        let qa: [QAPair]
    }

    struct Hit: Identifiable {
        let project: String
        let chunk: Chunk
        let score: Double
        /// The Q&A pair of this recommendation that matched best.
        let qa: QAPair?

        var id: String { project + "/" + chunk.id }
        var recommendation: Recommendation { Recommendation(project: project, chunk: chunk) }
    }

    /// How much a matching Q&A pair adds to its recommendation's own score.
    /// Below one: the recommendation is the source, the pair a paraphrase.
    static let qaWeight = 0.8

    static let stopwords: Set<String> = [
        // Dutch
        "de", "het", "een", "en", "of", "van", "in", "op", "met", "voor", "bij", "te", "aan",
        "als", "dat", "die", "dit", "om", "naar", "er", "is", "zijn", "wordt", "worden", "kan",
        "kunnen", "moet", "moeten", "wat", "welke", "wanneer", "hoe", "waarom", "wie", "ook",
        "niet", "geen", "door", "over", "tot", "uit", "dan", "nog", "heeft", "hebben", "je",
        "ik", "we", "mijn", "mag", "iemand", "patient", "patiënt", "patienten", "patiënten",
        // English
        "the", "an", "and", "or", "for", "with", "to", "on", "at", "by", "be", "are", "was",
        "were", "should", "may", "can", "what", "which", "when", "how", "why", "who", "not",
        "no", "from", "as", "that", "this", "these", "those", "it", "its", "of",
        "patients", "recommended", "considered", "indicated",
    ]

    /// Truncating long words is a crude stemmer that works for both languages
    /// at once: statin/statins/statine.
    static func terms(_ text: String) -> [String] {
        text.lowercased()
            .split { !$0.isLetter && !$0.isNumber }
            .map(String.init)
            .filter { $0.count >= 2 && !stopwords.contains($0) }
            .map { String($0.prefix(6)) }
    }

    private struct Doc {
        let corpus: Int
        let chunk: Int?      // index of the recommendation, or
        let qa: Int?         // index of the Q&A pair
        let tf: [String: Int]
        let length: Int
    }

    static func rank(_ corpora: [Corpus], query: String, limit: Int = 8) -> [Hit] {
        let queryTerms = Array(Set(terms(query)))
        guard !queryTerms.isEmpty else { return [] }

        var docs: [Doc] = []
        for (ci, corpus) in corpora.enumerated() {
            for (i, c) in corpus.chunks.enumerated() {
                let m = c.metadata
                let t = terms([c.text, m.section ?? "", m.tableTitle ?? "", m.disease ?? ""].joined(separator: " "))
                docs.append(Doc(corpus: ci, chunk: i, qa: nil, tf: counts(t), length: t.count))
            }
            for (i, q) in corpus.qa.enumerated() {
                let t = terms(q.question + " " + q.answer)
                docs.append(Doc(corpus: ci, chunk: nil, qa: i, tf: counts(t), length: t.count))
            }
        }
        guard !docs.isEmpty else { return [] }

        let n = Double(docs.count)
        let avgLength = Double(docs.reduce(0) { $0 + $1.length }) / n
        var idf: [String: Double] = [:]
        for q in queryTerms {
            let df = Double(docs.filter { $0.tf[q] != nil }.count)
            idf[q] = log((n - df + 0.5) / (df + 0.5) + 1)
        }

        func bm25(_ doc: Doc) -> Double {
            let k1 = 1.2, b = 0.75
            return queryTerms.reduce(0) { sum, q in
                guard let tf = doc.tf[q].map(Double.init) else { return sum }
                let norm = k1 * (1 - b + b * Double(doc.length) / avgLength)
                return sum + idf[q, default: 0] * tf * (k1 + 1) / (tf + norm)
            }
        }

        struct Score { var own = 0.0; var qa = 0.0; var qaIndex: Int? }
        var scores: [String: (corpus: Int, chunk: Int, score: Score)] = [:]

        for doc in docs {
            let s = bm25(doc)
            guard s > 0 else { continue }
            let corpus = corpora[doc.corpus]
            if let i = doc.chunk {
                let key = "\(doc.corpus)/\(i)"
                var entry = scores[key] ?? (doc.corpus, i, Score())
                entry.score.own = s
                scores[key] = entry
            } else if let qi = doc.qa,
                      let i = corpus.chunks.firstIndex(where: { corpus.qa[qi].belongs(to: $0.id) }) {
                let key = "\(doc.corpus)/\(i)"
                var entry = scores[key] ?? (doc.corpus, i, Score())
                if s > entry.score.qa {
                    entry.score.qa = s
                    entry.score.qaIndex = qi
                }
                scores[key] = entry
            }
        }

        struct Ranked { let corpus: Int; let chunk: Int; let score: Double; let qa: Int? }
        var ranked: [Ranked] = scores.values.map { entry in
            Ranked(corpus: entry.corpus, chunk: entry.chunk,
                   score: entry.score.own + qaWeight * entry.score.qa, qa: entry.score.qaIndex)
        }
        // Ties broken by position, so the order is stable between runs.
        ranked.sort { a, b in
            if a.score != b.score { return a.score > b.score }
            return (a.corpus, a.chunk) < (b.corpus, b.chunk)
        }
        return ranked.prefix(limit).map { r in
            let corpus = corpora[r.corpus]
            let qa: QAPair? = r.qa.map { corpus.qa[$0] }
            return Hit(project: corpus.project, chunk: corpus.chunks[r.chunk], score: r.score, qa: qa)
        }
    }

    private static func counts(_ terms: [String]) -> [String: Int] {
        terms.reduce(into: [:]) { $0[$1, default: 0] += 1 }
    }
}
