import NestKit
import SwiftUI

extension View {
    /// Off while the window is connected to a daemon on another machine, with why as its
    /// help (B105); unchanged on This Mac, or when `applies` is false.
    @ViewBuilder
    func localOnly(_ shell: Shell, when applies: Bool = true, _ why: (String) -> String)
        -> some View
    {
        if shell.isRemote && applies {
            disabled(true).help(why(shell.machineName))
        } else {
            self
        }
    }
}
