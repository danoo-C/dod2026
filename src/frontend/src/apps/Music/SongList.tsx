// The songs a visitor can pick (tech-spec 5.2; plan step 5): from
// `welcome.songs`, greyed out until downloaded, and all of them while no
// main screen is there to play them (`player_connected`).
import type { MusicPart, SongInfo } from "../../api/messages";
import { formatSeconds } from "../../api/clock";

export function SongList({
  songs,
  music,
  onPick,
}: {
  songs: readonly SongInfo[];
  music: MusicPart | null;
  onPick(id: string): void;
}) {
  const player = music?.player_connected ?? false;
  return (
    <>
      {music?.playing && (
        <div className="playing">
          <span className="eq" aria-hidden="true">
            <i />
            <i />
            <i />
            <i />
          </span>
          <span>Hrá: {music.title ?? music.song}</span>
        </div>
      )}
      {songs.length === 0 ? (
        <p className="note">Zatiaľ žiadne skladby.</p>
      ) : (
        <div className="songs">
          {songs.map((s) => (
            <button
              key={s.id}
              type="button"
              className="song"
              disabled={!s.ready || !player}
              aria-pressed={music?.song === s.id}
              onClick={() => onPick(s.id)}
            >
              <b>{s.title}</b>
              <span>{s.ready ? (music?.song === s.id ? "hrá" : "pustiť") : "ešte nie je stiahnutá"}</span>
              <span className="d">{s.length === null ? "–:––" : formatSeconds(s.length)}</span>
            </button>
          ))}
        </div>
      )}
      <p className="note">
        {player
          ? "Hudba hrá z reproduktora pri stánku. Šedé skladby ešte nie sú stiahnuté."
          : "Obrazovka stánku teraz nehrá, skladby sa nedajú pustiť."}
      </p>
    </>
  );
}
