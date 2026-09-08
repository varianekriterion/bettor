"use client";

import { LogOut, User } from "lucide-react";
import { useState } from "react";
import { AuthDialog } from "@/components/auth/auth-dialog";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";

export function AuthButton() {
  const { user, loading, configured, signOut } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogTab, setDialogTab] = useState<"signin" | "signup">("signin");

  const openAuth = (tab: "signin" | "signup") => {
    setDialogTab(tab);
    setDialogOpen(true);
  };

  if (!configured) {
    return (
      <span className="text-[11px] text-zinc-500" title="Set Supabase env vars">
        Auth off
      </span>
    );
  }

  if (loading) {
    return (
      <div className="h-8 w-20 animate-pulse rounded-full bg-zinc-800" aria-hidden />
    );
  }

  if (!user) {
    return (
      <>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="h-8 text-xs text-zinc-300"
            onClick={() => openAuth("signin")}
          >
            Sign in
          </Button>
          <Button
            size="sm"
            className="h-8 text-xs"
            onClick={() => openAuth("signup")}
          >
            Create account
          </Button>
        </div>
        <AuthDialog open={dialogOpen} onOpenChange={setDialogOpen} defaultTab={dialogTab} />
      </>
    );
  }

  const label =
    (user.user_metadata?.display_name as string | undefined) ||
    user.email?.split("@")[0] ||
    "Account";

  return (
    <>
      <div className="flex items-center gap-2">
        <span className="hidden items-center gap-1.5 text-xs text-zinc-400 sm:inline-flex">
          <User className="h-3.5 w-3.5" />
          {label}
        </span>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-1.5 text-xs text-zinc-400 hover:text-zinc-100"
          onClick={() => void signOut()}
        >
          <LogOut className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Sign out</span>
        </Button>
      </div>
      <AuthDialog open={dialogOpen} onOpenChange={setDialogOpen} defaultTab={dialogTab} />
    </>
  );
}
