import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold tracking-wide",
  {
    variants: {
      variant: {
        default: "bg-zinc-800 text-zinc-200 border border-zinc-700",
        positive: "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30",
        negative: "bg-rose-500/15 text-rose-400 border border-rose-500/30",
        warning: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
        league: "bg-sky-500/10 text-sky-300 border border-sky-500/25",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
