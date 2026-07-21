import Darwin
import NorthLightAgentCore

func require(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() {
        fputs("FAIL: \(message)\n", stderr)
        exit(1)
    }
}

var counter = InputActivityCounter()
counter.recordKeyboardActivity()
counter.recordKeyboardActivity()
counter.recordMouseActivity()

require(counter.keyboardCount == 2, "keyboard count should increment without event payload")
require(counter.mouseCount == 1, "mouse count should increment without event payload")

let drained = counter.drain()
require(drained.keyboardCount == 2, "drain should return keyboard count")
require(drained.mouseCount == 1, "drain should return mouse count")
require(counter.keyboardCount == 0, "drain should clear keyboard count")
require(counter.mouseCount == 0, "drain should clear mouse count")

print("NorthLightAgentCoreChecks OK")
