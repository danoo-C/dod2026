// Slovak words that change with the number.

/** 1 minútu, 2-4 minúty, 5+ minút (as in "o 3 minúty"). */
export function minutes(n: number): string {
  if (n === 1) return "1 minútu";
  if (n >= 2 && n <= 4) return `${n} minúty`;
  return `${n} minút`;
}

/** 1 človek, 2-4 ľudia, 5+ ľudí, 0 nikto. */
export function people(n: number): string {
  if (n === 0) return "nikto";
  if (n === 1) return "1 človek";
  if (n >= 2 && n <= 4) return `${n} ľudia`;
  return `${n} ľudí`;
}

/** A number with a decimal comma, as many decimals as `step` has: 1,5 · 0,25 · 3 */
export function decimal(value: number, step: number | null = null): string {
  const decimals = step === null ? 2 : Math.min(3, (String(step).split(".")[1] ?? "").length);
  return value.toLocaleString("sk-SK", { minimumFractionDigits: 0, maximumFractionDigits: decimals });
}
