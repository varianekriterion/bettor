import type { LeagueKey } from "@/types/betting";

export const LEAGUE_OPTIONS: { value: LeagueKey | "all"; label: string }[] = [
  { value: "all", label: "All leagues" },
  { value: "epl", label: "Premier League" },
  { value: "laliga", label: "La Liga" },
  { value: "bundesliga", label: "Bundesliga" },
  { value: "seriea", label: "Serie A" },
  { value: "ucl", label: "Champions League" },
  { value: "uel", label: "Europa League" },
];
