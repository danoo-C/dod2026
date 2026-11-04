// /internal/logging (tech-spec 4.5, 5.1; plan step 4): the fake terminal alone,
// full screen. The same terminal as the main screen's left panel; useful for
// testing it, or if a second monitor turns up.
//
// The backend sends the last 300 lines right after `welcome`, so the page
// opens (and reloads) on a full screen. The badge in the corner is the one
// honest thing on it: a dead backend or board shows up there.
import { LiveBadge } from "../components/Badge";
import { LiveTerminal } from "../components/Terminal";
import "../styles/logging.css";

export function Logging() {
  return (
    <div className="logging">
      <LiveTerminal />
      <div className="logging-badge">
        <LiveBadge />
      </div>
    </div>
  );
}
