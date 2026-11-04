// A short message from the server's refusals (store.ts: not_your_turn, …).
import { useStand } from "../api/useStand";

export function LiveToast() {
  const toast = useStand((s) => s.toast);
  if (toast === null) return null;
  return (
    <div key={toast.id} className="toast" role="status">
      {toast.text}
    </div>
  );
}
