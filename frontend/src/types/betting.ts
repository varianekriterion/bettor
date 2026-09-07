export type LeagueKey =
  | "ucl"
  | "epl"
  | "laliga"
  | "bundesliga"
  | "seriea"
  | "uel";

export type Outcome = "home" | "draw" | "away";

export type PredictionSource =
  | "forebet"
  | "predictz"
  | "windrawwin"
  | "betimate"
  | "footballwhispers";

export interface SourcePrediction {
  source: PredictionSource;
  home_prob: number;
  draw_prob: number;
  away_prob: number;
  pick: Outcome;
  confidence: number | null;
  scraped_at: string | null;
}

export interface BookmakerOdds {
  bookmaker: string;
  home: number;
  draw: number;
  away: number;
  last_update: string | null;
  totals?: TotalsLine | null;
}

export interface TotalsLine {
  line: number;
  over: number;
  under: number;
}

export interface MatchOdds {
  best_home: number;
  best_draw: number;
  best_away: number;
  bookmakers: BookmakerOdds[];
  totals_line?: number | null;
  best_over?: number | null;
  best_under?: number | null;
}

export interface OddsHistoryPoint {
  captured_at: string;
  outcome: Outcome;
  bookie_odds: number;
  bookie_implied_prob: number;
  consensus_prob: number;
  consensus_true_odds: number;
  delta_prob: number;
  ev_pct: number;
  is_positive_ev: boolean;
  market: "h2h" | "totals";
  line?: number | null;
  side?: "over" | "under" | null;
}

export interface OddsHistoryResponse {
  match_id: string;
  home_team: string;
  away_team: string;
  league: LeagueKey;
  league_name: string;
  outcome: Outcome;
  market: "h2h" | "totals";
  opening: OddsHistoryPoint | null;
  current: OddsHistoryPoint | null;
  points: OddsHistoryPoint[];
  value_shift_ev: number;
  into_positive_ev: boolean;
  source: "supabase" | "memory" | "synthetic";
}

export interface ConsensusScore {
  home: number;
  draw: number;
  away: number;
  pick: Outcome;
  confidence: number;
  source_weights: Record<string, number>;
}

export interface EdgeMetrics {
  outcome: Outcome;
  probability: number;
  odds: number;
  fair_prob: number;
  ev_pct: number;
  kelly_pct: number;
  is_positive_ev: boolean;
}

export interface MatchCard {
  id: string;
  league: LeagueKey;
  league_name: string;
  commence_time: string;
  home_team: string;
  away_team: string;
  odds: MatchOdds;
  predictions: SourcePrediction[];
  consensus: ConsensusScore;
  best_edge: EdgeMetrics;
  edges: EdgeMetrics[];
}

export interface MatrixSourceCell {
  home: number;
  draw: number;
  away: number;
  pick: Outcome;
}

export interface AggregatorMatrixRow {
  match_id: string;
  league: LeagueKey;
  home_team: string;
  away_team: string;
  commence_time: string;
  consensus: ConsensusScore;
  best_edge: EdgeMetrics;
  odds: { home: number; draw: number; away: number };
  sources: Record<string, MatrixSourceCell | null>;
}

export interface CalculatorRequest {
  bankroll: number;
  decimal_odds: number;
  win_probability: number;
  kelly_fraction: number;
}

export interface CalculatorResponse {
  ev_pct: number;
  ev_decimal: number;
  is_positive_ev: boolean;
  fair_odds: number;
  full_kelly_pct: number;
  fractional_kelly_pct: number;
  recommended_stake: number;
  expected_return: number;
  edge: number;
  kelly_fraction_used: number;
}

export interface SourcePerformance {
  source: string;
  league: string;
  total_predictions: number;
  correct: number;
  accuracy: number;
  brier_score: number;
  avg_ev_captured: number;
  last_30_days_accuracy: number;
  rank: number | null;
}

export interface LeaguePerformanceSummary {
  league: LeagueKey;
  league_name: string;
  sources: SourcePerformance[];
  best_source: string;
  consensus_accuracy: number;
}

export interface LeagueInfo {
  key: LeagueKey;
  name: string;
  short: string;
}

export interface BetJournalEntry {
  id: string;
  user_id?: string | null;
  match_id?: string | null;
  match_label?: string | null;
  outcome: Outcome;
  odds: number;
  stake: number;
  units?: number | null;
  consensus_prob: number;
  ev_pct: number;
  kelly_pct: number;
  result: "win" | "loss" | "push" | "pending";
  profit?: number | null;
  placed_at: string;
}

export type BetResult = BetJournalEntry["result"];


export const SOURCE_LABELS: Record<PredictionSource, string> = {
  forebet: "Forebet",
  predictz: "PredictZ",
  windrawwin: "WinDrawWin",
  betimate: "Betimate",
  footballwhispers: "FootballWhispers",
};

export const OUTCOME_LABELS: Record<Outcome, string> = {
  home: "Home",
  draw: "Draw",
  away: "Away",
};
