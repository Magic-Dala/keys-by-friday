import { ExternalLinkIcon, XIcon } from "@/components/icons";
import type { Listing } from "@/types/search";

function valueOrUnknown(value: string | number | undefined, suffix = "") {
  return value === undefined ? "Unknown" : `${value}${suffix}`;
}

export function ComparisonPanel({
  listings,
  onClose,
}: {
  listings: Listing[];
  onClose: () => void;
}) {
  return (
    <section className="comparisonPanel" aria-labelledby="comparison-title">
      <div className="sectionHeading">
        <div>
          <span className="sectionEyebrow">Decision view</span>
          <h2 id="comparison-title">Compare the details that matter</h2>
        </div>
        <button className="iconButton" type="button" onClick={onClose} aria-label="Close comparison">
          <XIcon />
        </button>
      </div>

      <div className="comparisonGrid">
        {listings.map((listing, index) => (
          <article className="comparisonColumn" key={listing.id}>
            <span className="rank">Option {index + 1}</span>
            <h3>{listing.title ?? listing.address ?? "Rental home"}</h3>
            <dl>
              <div>
                <dt>Monthly rent</dt>
                <dd>{listing.price === undefined ? "Unknown" : `$${Math.round(listing.price).toLocaleString()}`}</dd>
              </div>
              <div>
                <dt>Bedrooms</dt>
                <dd>{valueOrUnknown(listing.bedrooms)}</dd>
              </div>
              <div>
                <dt>Bathrooms</dt>
                <dd>{valueOrUnknown(listing.bathrooms)}</dd>
              </div>
              <div>
                <dt>Agent rationale</dt>
                <dd>{listing.reason ?? "Not enough evidence yet"}</dd>
              </div>
            </dl>
            {listing.url ? (
              <a className="sourceLink" href={listing.url} target="_blank" rel="noopener noreferrer">
                View source <ExternalLinkIcon className="buttonIcon" />
              </a>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
