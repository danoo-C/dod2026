// QR codes (tech-spec 6.4; plan step 3): the page's address, and the hotspot's
// Wi-Fi, so a phone joins it by scanning. Drawn in the browser, nothing
// from the internet.
import type { CSSProperties } from "react";
import { QRCodeSVG } from "qrcode.react";

/** The text a phone's camera reads as "join this Wi-Fi". `\ ; , : "` are escaped, as the format wants. */
export function wifiQr(ssid: string, password: string): string {
  const esc = (s: string) => s.replace(/([\\;,:"])/g, "\\$1");
  return `WIFI:S:${esc(ssid)};T:WPA;P:${esc(password)};;`;
}

export function Qr({ value, label, size = 64 }: { value: string; label?: string; size?: number | string }) {
  const style = { "--qr": typeof size === "number" ? `${size}px` : size } as CSSProperties;
  return (
    <figure className="qr" style={{ ...style, margin: 0 }}>
      <QRCodeSVG value={value} level="M" marginSize={2} bgColor="#eef0fb" fgColor="#0c0d18" title={label ?? value} />
      {label !== undefined && <figcaption>{label}</figcaption>}
    </figure>
  );
}
