import Foundation

/// A Vancouver-style reference split into clickable parts.
///
/// Port of src/lib/references.js. The text comes out of the PDF→markdown
/// conversion, which damages DOIs (inserted spaces, dropped hyphens), so a DOI
/// is a bonus link and the PubMed title search is the reliable way out.
struct ParsedReference: Hashable {
    let number: Int
    let raw: String
    var authors: String?
    var title: String?
    var journal: String?
    var year: String?
    var doi: String?
    var pmid: String?

    init(_ entry: ReferenceEntry) {
        number = entry.id
        raw = entry.text.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        doi = Self.extractDoi(raw)
        pmid = Self.firstGroup(#"\bPMID:?\s*(\d{4,9})\b"#, in: raw, options: .caseInsensitive)
        parseBody()
    }

    private static func firstGroup(_ pattern: String, in text: String, options: NSRegularExpression.Options = []) -> String? {
        guard let re = try? NSRegularExpression(pattern: pattern, options: options),
              let m = re.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
              m.numberOfRanges > 1, let r = Range(m.range(at: 1), in: text) else { return nil }
        return String(text[r])
    }

    private static func extractDoi(_ text: String) -> String? {
        guard let start = text.range(of: #"10\.\d{4}"#, options: .regularExpression) else { return nil }
        // The DOI is always the last thing on a reference line.
        var doi = String(text[start.lowerBound...]).replacingOccurrences(of: #"\s+"#, with: "", options: .regularExpression)
        while let last = doi.last, ".,;)]".contains(last) { doi.removeLast() }
        // A dropped hyphen leaves an implausibly long digit run; those 404.
        if doi.range(of: #"\d{9,}"#, options: .regularExpression) != nil { return nil }
        return doi.range(of: #"^10\.\d{4,9}/\S{3,}$"#, options: .regularExpression) != nil ? doi : nil
    }

    private mutating func parseBody() {
        // Drop the trailing URL so it cannot be mistaken for the title.
        var body = raw.replacingOccurrences(of: #"\s*https?:\s*//.*$"#, with: "", options: [.regularExpression, .caseInsensitive])
        body = body.trimmingCharacters(in: .whitespaces)

        var rest = body
        if let m = body.range(of: #"^.{0,400}?\bet al\.\s+"#, options: .regularExpression) {
            authors = String(body[m]).replacingOccurrences(of: #"\.\s+$"#, with: "", options: .regularExpression)
            rest = String(body[m.upperBound...])
        } else if let m = body.range(of: #"^[^.]{3,300}?\.\s+"#, options: .regularExpression),
                  body[m].range(of: #"^(?:[a-z]{1,4}\s+){0,3}[A-Z][\p{L}'’-]+\s+[A-Z]{1,3}\b"#, options: .regularExpression) != nil {
            // Short author list: "Smith AB, Jones CD." — starts like a name.
            authors = String(body[m]).replacingOccurrences(of: #"\.\s+$"#, with: "", options: .regularExpression)
            rest = String(body[m.upperBound...])
        }

        // The journal segment carries "Year;Volume"; the title is the
        // sentence before it.
        if let yv = rest.range(of: #"\b(?:19|20)\d{2}\s*;"#, options: .regularExpression) {
            year = String(rest[yv].prefix(4))
            let head = String(rest[..<yv.lowerBound])
            if let cut = head.range(of: ". ", options: .backwards) {
                title = String(head[..<cut.lowerBound])
                journal = String(head[cut.upperBound...]).trimmingCharacters(in: .whitespaces)
            } else {
                title = head
            }
        } else if let cut = rest.range(of: ". ") {
            title = String(rest[..<cut.lowerBound])
        } else {
            title = rest
        }
        title = title?.trimmingCharacters(in: CharacterSet(charactersIn: ". ")).nilIfEmpty
        journal = journal?.nilIfEmpty
    }

    /// PMID straight to the record, otherwise a title search: PubMed resolves
    /// that to the one article, where a damaged DOI would 404.
    var pubmedURL: URL {
        if let pmid { return URL(string: "https://pubmed.ncbi.nlm.nih.gov/\(pmid)/")! }
        let term: String
        if let title, title.count > 15 { term = "\(title)[Title]" } else { term = doi ?? String(raw.prefix(300)) }
        return Self.url("https://pubmed.ncbi.nlm.nih.gov/", query: "term", term)
    }

    var doiURL: URL? { doi.flatMap { URL(string: "https://doi.org/\($0)") } }

    var scholarURL: URL {
        Self.url("https://scholar.google.com/scholar", query: "q", String((title ?? raw).prefix(300)))
    }

    var shortCitation: String {
        var bits: [String] = []
        if let authors { bits.append(authors.count > 40 ? String(authors.prefix(40)) + "…" : authors) }
        let tail = [journal, year].compactMap { $0 }.joined(separator: " ")
        if !tail.isEmpty { bits.append(tail) }
        return bits.joined(separator: " · ")
    }

    private static func url(_ base: String, query name: String, _ value: String) -> URL {
        var c = URLComponents(string: base)!
        c.queryItems = [URLQueryItem(name: name, value: value)]
        return c.url!
    }
}

extension String {
    var nilIfEmpty: String? { isEmpty ? nil : self }
}
