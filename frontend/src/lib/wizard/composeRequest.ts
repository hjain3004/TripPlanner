import type { WizardData } from "./types";

export function composeRawRequest(data: WizardData): string {
  const parts: string[] = [];

  if (data.origin && data.destination) {
    parts.push(`${data.origin} to ${data.destination}`);
  }

  if (data.startDate) {
    if (data.endDate && data.endDate !== data.startDate) {
      parts.push(`${data.startDate} to ${data.endDate}`);
    } else {
      parts.push(data.startDate);
    }
  }

  if (data.travelers > 1) {
    parts.push(`${data.travelers} travelers`);
  }

  if (data.budgetStyle !== "balanced") {
    parts.push(data.budgetStyle);
  }

  if (data.pace !== "moderate") {
    parts.push(`${data.pace} pace`);
  }

  if (data.interests.length > 0) {
    parts.push(data.interests.join(", "));
  }

  return parts.join(", ");
}

export function parseWallet(
  data: WizardData
): { card_ids: string[]; points_balances: Record<string, number> } | undefined {
  if (data.cardIds.length === 0 && Object.keys(data.pointsBalances).length === 0) {
    return undefined;
  }
  return {
    card_ids: data.cardIds,
    points_balances: data.pointsBalances,
  };
}
