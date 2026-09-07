import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL?.trim();
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY?.trim();

export const isSupabaseConfigured = Boolean(url && anonKey);

let client: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (!isSupabaseConfigured) return null;
  if (!client) {
    client = createClient(url!, anonKey!, {
      auth: {
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
      },
    });
  }
  return client;
}

/** Ensure profile row exists so bet_journal.user_id FK succeeds under RLS. */
async function ensureProfile(userId: string, displayName?: string | null) {
  const supabase = getSupabase();
  if (!supabase) return;
  const { error } = await supabase.from("profiles").upsert(
    {
      id: userId,
      display_name: displayName || "Bettor",
    },
    { onConflict: "id" }
  );
  if (error) {
    // Trigger may have already created the row; ignore unique conflicts.
    console.debug("ensureProfile:", error.message);
  }
}

/** Ensure a session exists for RLS-backed journal writes (anonymous if enabled). */
export async function ensureJournalSession(): Promise<{
  userId: string | null;
  mode: "supabase" | "local";
  message?: string;
}> {
  const supabase = getSupabase();
  if (!supabase) {
    return {
      userId: null,
      mode: "local",
      message: "Supabase not configured — journal saved in this browser only.",
    };
  }

  const { data: existing } = await supabase.auth.getSession();
  if (existing.session?.user?.id) {
    await ensureProfile(
      existing.session.user.id,
      existing.session.user.email?.split("@")[0]
    );
    return { userId: existing.session.user.id, mode: "supabase" };
  }

  const { data, error } = await supabase.auth.signInAnonymously();
  if (error || !data.user) {
    return {
      userId: null,
      mode: "local",
      message:
        error?.message ||
        "Anonymous auth unavailable — enable it in Supabase Auth, or sign in. Journal falls back to local storage.",
    };
  }

  await ensureProfile(data.user.id, "Anonymous");
  return { userId: data.user.id, mode: "supabase" };
}
