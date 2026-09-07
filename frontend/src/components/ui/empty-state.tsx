import { cn } from "@/lib/utils";

export function EmptyState({
  title,
  description,
  className,
}: {
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center px-4 py-12 text-center",
        className
      )}
    >
      <p className="text-sm font-medium text-zinc-300">{title}</p>
      {description && (
        <p className="mt-1 max-w-md text-xs text-zinc-500">{description}</p>
      )}
    </div>
  );
}
