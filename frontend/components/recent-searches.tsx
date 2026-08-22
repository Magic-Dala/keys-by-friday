import type { RecentSearch } from "@/types/search";

export interface RecentSearchesProps {
  items: RecentSearch[];
  loading: boolean;
  error?: string;
  onRetry: () => void;
  onViewResults: (search: RecentSearch) => void;
  onContinueSearch: (search: RecentSearch) => void;
}

function updatedLabel(timestamp: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

function countLabel(count: number, singular: string, plural: string) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function priceRange(search: RecentSearch) {
  const ranges = search.listings.flatMap((listing) => {
    if (
      listing.priceMin === undefined ||
      listing.priceMax === undefined ||
      listing.priceMin > listing.priceMax
    ) return [];
    return [listing.priceMin, listing.priceMax];
  });
  if (!ranges.length) return undefined;

  const minimum = Math.min(...ranges);
  const maximum = Math.max(...ranges);
  const format = (value: number) => `$${Math.round(value).toLocaleString()}`;
  return minimum === maximum ? format(minimum) : `${format(minimum)} – ${format(maximum)}`;
}

function commuteLabel(status: RecentSearch["lastCommuteStatus"]) {
  if (status === "requires_input") return "Commute details needed";
  if (status === "available") return "Commute data available";
  if (status === "partial") return "Partial commute data";
  if (status === "unavailable") return "Commute data unavailable";
  if (status === "unknown") return "Commute status unknown";
  return undefined;
}

function RecentSearchItem({
  search,
  onViewResults,
  onContinueSearch,
}: {
  search: RecentSearch;
  onViewResults: (search: RecentSearch) => void;
  onContinueSearch: (search: RecentSearch) => void;
}) {
  const updated = updatedLabel(search.updatedAt);
  const range = priceRange(search);
  const commute = commuteLabel(search.lastCommuteStatus);

  return (
    <li className="recentSearchItem">
      <div className="recentSearchHeading">
        <div>
          <h3>Rental search</h3>
          <p>Updated {updated} · {countLabel(search.turnCount, "turn", "turns")}</p>
        </div>
      </div>
      <div className="recentSearchFacts">
        <span>{countLabel(search.listings.length, "latest home", "latest homes")}</span>
        {range ? <span>{range}</span> : null}
        {commute ? <span>{commute}</span> : null}
      </div>
      <div className="recentSearchActions">
        <button type="button" onClick={() => onViewResults(search)}>
          View Results
        </button>
        <button type="button" onClick={() => onContinueSearch(search)}>
          Continue Search
        </button>
      </div>
    </li>
  );
}

export function RecentSearches({
  items,
  loading,
  error,
  onRetry,
  onViewResults,
  onContinueSearch,
}: RecentSearchesProps) {
  const visibleItems = items.slice(0, 3);

  return (
    <section
      className="railCard recentSearchesCard"
      aria-labelledby="recent-searches-title"
      aria-busy={loading}
    >
      <div className="railCardHeading">
        <div>
          <span className="sectionEyebrow">Your account</span>
          <h2 id="recent-searches-title">Recent Searches</h2>
        </div>
      </div>

      {loading && items.length === 0 ? (
        <div className="recentSearchesLoading" role="status" aria-live="polite">
          <span className="loadingDots" aria-hidden="true"><i /><i /><i /></span>
          <span>Loading recent searches…</span>
        </div>
      ) : null}

      {loading && items.length > 0 ? (
        <p className="recentSearchesRefreshing" role="status" aria-live="polite">
          Refreshing recent searches…
        </p>
      ) : null}

      {error ? (
        <div className="recentSearchesError" role="alert">
          <p>{error}</p>
          <button type="button" onClick={onRetry}>Retry</button>
        </div>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <p className="recentSearchesEmpty">
          <strong>No recent searches yet.</strong>
          <span>Start a rental search and it’ll appear here.</span>
        </p>
      ) : null}

      {visibleItems.length > 0 ? (
        <ol className="recentSearchesList">
          {visibleItems.map((search) => (
            <RecentSearchItem
              key={search.conversationId}
              search={search}
              onViewResults={onViewResults}
              onContinueSearch={onContinueSearch}
            />
          ))}
        </ol>
      ) : null}

      {items.length > visibleItems.length ? (
        <p className="recentSearchesLimit">Showing the 3 most recent searches</p>
      ) : null}
    </section>
  );
}
