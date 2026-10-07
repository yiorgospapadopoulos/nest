import Foundation

/// A multipart/form-data body with one file field.
struct MultipartForm {
    let boundary: String
    let body: Data

    var contentType: String { "multipart/form-data; boundary=\(boundary)" }

    init(
        fieldName: String, filename: String, mediaType: String, data: Data,
        boundary: String = "harness-\(UUID().uuidString)"
    ) {
        self.boundary = boundary
        // Quotes and line breaks would end the header early.
        let unsafe = "\"\r\n".unicodeScalars
        let safeName = String(
            String.UnicodeScalarView(filename.unicodeScalars.filter { !unsafe.contains($0) }))
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(
            Data(
                "Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(safeName)\"\r\n"
                    .utf8))
        body.append(Data("Content-Type: \(mediaType)\r\n\r\n".utf8))
        body.append(data)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        self.body = body
    }
}
