import {
  CheckIcon,
  CompareIcon,
  ExternalLinkIcon,
  HeartIcon,
} from "@/components/icons";
import type { Listing } from "@/types/search";

interface ListingCardProps {
  listing: Listing;
  rank: number;
  saved: boolean;
  selected: boolean;
  onSave: (listing: Listing) => void;
  onSelect: (listing: Listing) => void;
}

function formatPrice(price: number | undefined) {
  if (price === undefined) return "Price unknown";
  return `$${Math.round(price).toLocaleString()}`;
}

function formatRoom(value: number | undefined, noun: string) {
  if (value === undefined) return `${noun} unknown`;
  return `${Number.isInteger(value) ? value : value.toFixed(1)} ${noun}`;
}

function matchScore(score: number | undefined) {
  if (score === undefined) return undefined;
  const normalized = score <= 10 ? score * 10 : score;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

export function ListingCard({
  listing,
  rank,
  saved,
  selected,
  onSave,
  onSelect,
}: ListingCardProps) {
  const score = matchScore(listing.score);
  const reasons = listing.reason
    ?.split(";")
    .map((reason) => reason.trim())
    .filter(Boolean)
    .slice(0, 3);

  return (
    <article className="listingCard">
      <div className="listingTopline">
        <span className="rank">#{rank} recommendation</span>
        {score !== undefined ? <span className="matchScore">{score}% match</span> : null}
      </div>

      <div className="listingHeading">
        <div>
          <h3>{listing.title ?? listing.address ?? "Rental home"}</h3>
          {listing.title && listing.address ? <p>{listing.address}</p> : null}
        </div>
        <p className="listingPrice">
          <strong>{formatPrice(listing.price)}</strong>
          {listing.price !== undefined ? <span>/ month</span> : null}
        </p>
      </div>

      <dl className="listingFacts">
        <div>
          <dt>Bedrooms</dt>
          <dd>{formatRoom(listing.bedrooms, "bed")}</dd>
        </div>
        <div>
          <dt>Bathrooms</dt>
          <dd>{formatRoom(listing.bathrooms, "bath")}</dd>
        </div>
        <div>
          <dt>Evidence</dt>
          <dd className={reasons?.length ? "confirmed" : "unknown"}>
            {reasons?.length ? (
              <>
                <CheckIcon className="inlineIcon" /> Reviewed
              </>
            ) : (
              "Not provided"
            )}
          </dd>
        </div>
      </dl>

      {reasons?.length ? (
        <div className="evidenceBlock">
          <span>Why it fits</span>
          <ul>
            {reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="missingNote">Important fit details are still unknown and should be verified.</p>
      )}

      <div className="listingActions">
        <button
          className={saved ? "actionButton isActive" : "actionButton"}
          type="button"
          aria-pressed={saved}
          onClick={() => onSave(listing)}
        >
          <HeartIcon className="buttonIcon" fill={saved ? "currentColor" : "none"} />
          {saved ? "Saved" : "Save"}
        </button>
        <button
          className={selected ? "actionButton isActive" : "actionButton"}
          type="button"
          aria-pressed={selected}
          onClick={() => onSelect(listing)}
        >
          <CompareIcon className="buttonIcon" />
          {selected ? "Comparing" : "Compare"}
        </button>
        {listing.url ? (
          <a className="sourceLink" href={listing.url} target="_blank" rel="noopener noreferrer">
            View source
            <ExternalLinkIcon className="buttonIcon" />
          </a>
        ) : null}
      </div>
    </article>
  );
}
