import Testing

@testable import NestKit

@Suite struct SidebarWidthTests {
    @Test func widthsStayWithinTheirBounds() {
        let roomy = 2000.0
        #expect(SidebarWidth.clamp(300, available: roomy) == 300)
        #expect(SidebarWidth.clamp(120, available: roomy) == SidebarWidth.minimum)
        #expect(SidebarWidth.clamp(900, available: roomy) == SidebarWidth.maximum)
        #expect(SidebarWidth.minimum < SidebarWidth.standard)
        #expect(SidebarWidth.standard < SidebarWidth.maximum)
    }

    @Test func theWorkspaceKeepsRoomForAPane() {
        // A narrow window leaves the workspace its minimum.
        let available = 650.0
        let widest = available - SidebarWidth.minimumWorkspace
        #expect(SidebarWidth.clamp(420, available: available) == widest)
        #expect(SidebarWidth.clamp(250, available: available) == 250)
        // Never below the minimum, even when the window is narrower still.
        #expect(SidebarWidth.clamp(300, available: 300) == SidebarWidth.minimum)
    }

    @Test func anUnmeasuredWindowOnlyAppliesTheFixedBounds() {
        #expect(SidebarWidth.clamp(400, available: 0) == 400)
        #expect(SidebarWidth.clamp(900, available: 0) == SidebarWidth.maximum)
    }

    @Test func aStoredWidthIsReadBackWithinBounds() {
        #expect(SidebarWidth.stored(nil) == SidebarWidth.standard)
        #expect(SidebarWidth.stored("wide") == SidebarWidth.standard)
        #expect(SidebarWidth.stored("nan") == SidebarWidth.standard)
        #expect(SidebarWidth.stored("312.5") == 312.5)
        #expect(SidebarWidth.stored("50") == SidebarWidth.minimum)
        #expect(SidebarWidth.stored("5000") == SidebarWidth.maximum)
    }

    @Test func stepsMoveByAFixedAmount() {
        #expect(SidebarWidth.stepped(300, by: 1) == 300 + SidebarWidth.step)
        #expect(SidebarWidth.stepped(300, by: -1) == 300 - SidebarWidth.step)
        #expect(SidebarWidth.stepped(SidebarWidth.maximum, by: 1) == SidebarWidth.maximum)
        #expect(SidebarWidth.stepped(SidebarWidth.minimum, by: -1) == SidebarWidth.minimum)
    }
}
