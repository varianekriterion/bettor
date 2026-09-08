"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/contexts/auth-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultTab?: "signin" | "signup";
};

export function AuthDialog({ open, onOpenChange, defaultTab = "signin" }: Props) {
  const { signIn, signUp, configured } = useAuth();
  const [tab, setTab] = useState<"signin" | "signup">(defaultTab);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const resetForm = () => {
    setError(null);
    setMessage(null);
  };

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    resetForm();
    setLoading(true);
    try {
      if (tab === "signin") {
        const result = await signIn(email.trim(), password);
        if (result.error) {
          setError(result.error);
          return;
        }
        onOpenChange(false);
      } else {
        if (password.length < 6) {
          setError("Password must be at least 6 characters.");
          return;
        }
        const result = await signUp(email.trim(), password, displayName);
        if (result.error) {
          setError(result.error);
          return;
        }
        if (result.needsConfirmation) {
          setMessage("Account created — check your email to confirm, then sign in.");
          setTab("signin");
          return;
        }
        onOpenChange(false);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) resetForm();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{tab === "signin" ? "Sign in" : "Create account"}</DialogTitle>
          <DialogDescription>
            {configured
              ? "Sync your bet journal, slip OCR, and chat history."
              : "Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY to .env.local."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex gap-1 border-b border-zinc-800 px-5 pb-0 pt-2">
          {(["signin", "signup"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => {
                setTab(t);
                resetForm();
              }}
              className={cn(
                "border-b-2 px-3 py-2 text-sm transition-colors",
                tab === t
                  ? "border-emerald-400 text-emerald-300"
                  : "border-transparent text-zinc-500 hover:text-zinc-300"
              )}
            >
              {t === "signin" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>

        <form onSubmit={onSubmit} className="space-y-4 px-5 py-5">
          {tab === "signup" && (
            <div className="space-y-1.5">
              <Label htmlFor="display-name">Display name</Label>
              <Input
                id="display-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="Your name"
                autoComplete="name"
              />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="auth-email">Email</Label>
            <Input
              id="auth-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="auth-password">Password</Label>
            <Input
              id="auth-password"
              type="password"
              required
              minLength={6}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={tab === "signup" ? "At least 6 characters" : "••••••••"}
              autoComplete={tab === "signup" ? "new-password" : "current-password"}
            />
          </div>

          {error && <p className="text-sm text-rose-400">{error}</p>}
          {message && <p className="text-sm text-emerald-400">{message}</p>}

          <Button type="submit" className="w-full" disabled={loading || !configured}>
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : tab === "signin" ? (
              "Sign in"
            ) : (
              "Create account"
            )}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
