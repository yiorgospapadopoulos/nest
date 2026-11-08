import Testing

@testable import NestKit

private final class Field {}

@Suite struct FocusReturnTests {
    /// The palette opening a chat's changes, or a review its publish sheet, replaces one
    /// sheet with another: closing must still return to where the user was before the first.
    @Test func aSheetReplacedByAnotherReturnsToWhereTheFirstOpenedFrom() {
        let composer = Field()
        let paletteField = Field()
        var focus = FocusReturn<Field>()
        focus.opened(.sheet, from: composer)
        focus.opened(.sheet, from: paletteField)
        #expect(focus.closed(.sheet) === composer)
        #expect(focus.closed(.sheet) == nil)
    }

    @Test func aSheetOverSettingsReturnsIntoSettingsThenSettingsReturnsToTheWindow() {
        let composer = Field()
        let settingsButton = Field()
        var focus = FocusReturn<Field>()
        focus.opened(.settings, from: composer)
        focus.opened(.sheet, from: settingsButton)
        #expect(focus.closed(.sheet) === settingsButton)
        #expect(focus.closed(.settings) === composer)
    }

    @Test func aViewThatWentAwayIsNotHeldOrReturned() {
        var focus = FocusReturn<Field>()
        var pane: Field? = Field()
        focus.opened(.sheet, from: pane)
        pane = nil
        #expect(focus.closed(.sheet) == nil)
    }
}
