// The 8x8 as 16 hex characters: 8 rows, row 0 on top, bit 7 the leftmost
// pixel – the same in the drawing, the state and the preview (backend.md 9).

export const SIZE = 8;
export const EMPTY = "0000000000000000";

/** The 64 pixels, row by row, left to right; anything malformed is all off. */
export function decodeMatrix(hex: string): boolean[] {
  if (!/^[0-9a-fA-F]{16}$/.test(hex)) return Array<boolean>(SIZE * SIZE).fill(false);
  const pixels: boolean[] = [];
  for (let row = 0; row < SIZE; row++) {
    const bits = parseInt(hex.slice(row * 2, row * 2 + 2), 16);
    for (let x = 0; x < SIZE; x++) pixels.push((bits & (0x80 >> x)) !== 0);
  }
  return pixels;
}

/** 64 pixels back to 16 lower-case hex characters. */
export function encodeMatrix(pixels: readonly boolean[]): string {
  let hex = "";
  for (let row = 0; row < SIZE; row++) {
    let bits = 0;
    for (let x = 0; x < SIZE; x++) if (pixels[row * SIZE + x]) bits |= 0x80 >> x;
    hex += bits.toString(16).padStart(2, "0");
  }
  return hex;
}

/** The drawing with one pixel set to `on`. */
export function withPixel(hex: string, index: number, on: boolean): string {
  const pixels = decodeMatrix(hex);
  pixels[index] = on;
  return encodeMatrix(pixels);
}
