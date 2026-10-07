// Renders the app icon: a guideline page with a heartbeat line and an AI
// sparkle on a warm amber gradient.
//
//   swift ios/scripts/make_icon.swift <output.png>
import AppKit
import CoreGraphics

let size: CGFloat = 1024
let out = CommandLine.arguments.dropFirst().first ?? "AppIcon.png"
let space = CGColorSpace(name: CGColorSpace.sRGB)!
let ctx = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8, bytesPerRow: 0,
                    space: space, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!

func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat, _ a: CGFloat = 1) -> CGColor {
    CGColor(colorSpace: space, components: [r / 255, g / 255, b / 255, a])!
}

// CoreGraphics' origin is bottom-left; flip so y grows downwards like a design tool.
ctx.translateBy(x: 0, y: size)
ctx.scaleBy(x: 1, y: -1)

// Background: amber, lighter top-left to burnt orange bottom-right.
let bg = CGGradient(colorsSpace: space, colors: [rgb(246, 190, 98), rgb(222, 140, 56), rgb(176, 84, 34)] as CFArray,
                    locations: [0, 0.55, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 0, y: 0), end: CGPoint(x: size, y: size), options: [])

// Soft light in the top-left corner for depth.
let glow = CGGradient(colorsSpace: space, colors: [rgb(255, 240, 210, 0.45), rgb(255, 240, 210, 0)] as CFArray, locations: [0, 1])!
ctx.drawRadialGradient(glow, startCenter: CGPoint(x: 260, y: 220), startRadius: 0,
                       endCenter: CGPoint(x: 260, y: 220), endRadius: 620, options: [])

// The page, with a shadow and a folded corner.
let page = CGRect(x: 262, y: 196, width: 500, height: 640)
let fold: CGFloat = 120
let pagePath = CGMutablePath()
pagePath.move(to: CGPoint(x: page.minX + 48, y: page.minY))
pagePath.addLine(to: CGPoint(x: page.maxX - fold, y: page.minY))
pagePath.addLine(to: CGPoint(x: page.maxX, y: page.minY + fold))
pagePath.addLine(to: CGPoint(x: page.maxX, y: page.maxY - 48))
pagePath.addQuadCurve(to: CGPoint(x: page.maxX - 48, y: page.maxY), control: CGPoint(x: page.maxX, y: page.maxY))
pagePath.addLine(to: CGPoint(x: page.minX + 48, y: page.maxY))
pagePath.addQuadCurve(to: CGPoint(x: page.minX, y: page.maxY - 48), control: CGPoint(x: page.minX, y: page.maxY))
pagePath.addLine(to: CGPoint(x: page.minX, y: page.minY + 48))
pagePath.addQuadCurve(to: CGPoint(x: page.minX + 48, y: page.minY), control: CGPoint(x: page.minX, y: page.minY))
pagePath.closeSubpath()

ctx.saveGState()
ctx.setShadow(offset: CGSize(width: 0, height: 26), blur: 60, color: rgb(90, 40, 10, 0.45))
ctx.addPath(pagePath)
ctx.setFillColor(rgb(255, 251, 244))
ctx.fillPath()
ctx.restoreGState()

// Folded corner.
let foldPath = CGMutablePath()
foldPath.move(to: CGPoint(x: page.maxX - fold, y: page.minY))
foldPath.addLine(to: CGPoint(x: page.maxX - fold, y: page.minY + fold - 22))
foldPath.addQuadCurve(to: CGPoint(x: page.maxX - fold + 22, y: page.minY + fold),
                      control: CGPoint(x: page.maxX - fold, y: page.minY + fold))
foldPath.addLine(to: CGPoint(x: page.maxX, y: page.minY + fold))
foldPath.closeSubpath()
ctx.addPath(foldPath)
ctx.setFillColor(rgb(240, 214, 176))
ctx.fillPath()

// Text lines.
ctx.setLineCap(.round)
ctx.setStrokeColor(rgb(214, 190, 160))
ctx.setLineWidth(30)
for (y, width) in [(300.0, 280.0), (700.0, 330.0), (775.0, 230.0)] {
    ctx.move(to: CGPoint(x: page.minX + 70, y: y))
    ctx.addLine(to: CGPoint(x: page.minX + 70 + width, y: y))
}
ctx.strokePath()

// Heartbeat across the middle of the page.
ctx.setStrokeColor(rgb(214, 64, 52))
ctx.setLineWidth(34)
ctx.setLineJoin(.round)
let midY: CGFloat = 520
let ecg: [(CGFloat, CGFloat)] = [(page.minX + 56, midY), (page.minX + 160, midY), (page.minX + 205, midY - 70),
                                 (page.minX + 255, midY + 110), (page.minX + 310, midY - 170), (page.minX + 360, midY + 40),
                                 (page.minX + 395, midY), (page.maxX - 56, midY)]
ctx.move(to: CGPoint(x: ecg[0].0, y: ecg[0].1))
for p in ecg.dropFirst() { ctx.addLine(to: CGPoint(x: p.0, y: p.1)) }
ctx.strokePath()

// AI sparkle, top-right, overlapping the page corner.
func sparkle(center: CGPoint, radius: CGFloat, waist: CGFloat) -> CGPath {
    let path = CGMutablePath()
    let pts: [CGPoint] = [
        CGPoint(x: 0, y: -radius), CGPoint(x: waist, y: -waist), CGPoint(x: radius, y: 0), CGPoint(x: waist, y: waist),
        CGPoint(x: 0, y: radius), CGPoint(x: -waist, y: waist), CGPoint(x: -radius, y: 0), CGPoint(x: -waist, y: -waist),
    ]
    path.move(to: CGPoint(x: center.x + pts[0].x, y: center.y + pts[0].y))
    for i in stride(from: 1, to: pts.count + 1, by: 2) {
        let control = pts[i % pts.count]
        let end = pts[(i + 1) % pts.count]
        path.addQuadCurve(to: CGPoint(x: center.x + end.x, y: center.y + end.y),
                          control: CGPoint(x: center.x + control.x * 0.35, y: center.y + control.y * 0.35))
    }
    path.closeSubpath()
    return path
}

ctx.saveGState()
ctx.setShadow(offset: .zero, blur: 40, color: rgb(255, 255, 230, 0.9))
ctx.addPath(sparkle(center: CGPoint(x: 778, y: 214), radius: 128, waist: 34))
ctx.setFillColor(rgb(255, 255, 255))
ctx.fillPath()
ctx.addPath(sparkle(center: CGPoint(x: 868, y: 360), radius: 58, waist: 16))
ctx.fillPath()
ctx.restoreGState()

let image = ctx.makeImage()!
let rep = NSBitmapImageRep(cgImage: image)
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
print("wrote \(out)")
