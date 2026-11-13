// Who made the stand: the school's logo, and the author's Instagram. Bundled
// like the fonts, nothing loaded from the internet. The originals are in
// logos/ at the project's root; these are cut down for the web (the logo cut
// round, transparent around it; the Instagram card 640 px wide).
import instagramCard from "../assets/instagram-danoodnk.png";
import schoolLogo from "../assets/spse-logo.webp";

export const SCHOOL = "SPŠE Košice";
export const INSTAGRAM = "danoodnk";
/** What the card's QR code opens (read off the card itself). */
export const INSTAGRAM_URL = "https://www.instagram.com/danoodnk?utm_source=qr";

export function SchoolLogo({ size }: { size: number }) {
  return <img className="school-logo" src={schoolLogo} alt={SCHOOL} width={size} height={size} />;
}

/** The main screen: the Instagram card, a QR code to scan from the corridor. */
export function AuthorCard() {
  return (
    <figure className="author">
      <img src={instagramCard} alt={`Instagram @${INSTAGRAM}`} width={640} height={735} />
      <figcaption>Autor projektu</figcaption>
    </figure>
  );
}

/** The phone: a QR code can't be scanned from its own screen, so a link. */
export function AuthorLink() {
  return (
    <a className="author-link" href={INSTAGRAM_URL} target="_blank" rel="noopener noreferrer">
      <span>Autor projektu</span>
      <b>@{INSTAGRAM}</b>
    </a>
  );
}
