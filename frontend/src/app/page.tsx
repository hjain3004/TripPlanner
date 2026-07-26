import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen bg-canvas font-ui text-text">
      <div className="mx-auto max-w-2xl px-6 py-24 text-center">
        <h1 className="font-display text-5xl leading-tight text-text mb-4">
          TripPlanner
        </h1>
        <p className="text-lg text-text-muted mb-8">
          A travel planner that knows your credit cards.
        </p>
        <div className="flex items-center justify-center gap-4">
          <Link
            href="/plan"
            className="inline-flex items-center justify-center px-6 py-3 rounded-sm bg-primary text-on-primary text-sm font-medium hover:opacity-90 transition-opacity"
          >
            Plan a trip
          </Link>
          <Link
            href="/kitchen-sink"
            className="inline-flex items-center justify-center px-6 py-3 rounded-sm border border-border bg-surface text-text text-sm font-medium hover:bg-accent-2 transition-colors"
          >
            Component Library
          </Link>
        </div>
      </div>
    </div>
  );
}
