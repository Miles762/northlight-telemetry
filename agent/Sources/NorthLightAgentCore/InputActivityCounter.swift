public struct InputActivityCounter {
    public private(set) var keyboardCount = 0
    public private(set) var mouseCount = 0

    public init() {}

    public mutating func recordKeyboardActivity() {
        keyboardCount += 1
    }

    public mutating func recordMouseActivity() {
        mouseCount += 1
    }

    public mutating func drain() -> (keyboardCount: Int, mouseCount: Int) {
        let counts = (keyboardCount, mouseCount)
        reset()
        return counts
    }

    public mutating func reset() {
        keyboardCount = 0
        mouseCount = 0
    }
}
