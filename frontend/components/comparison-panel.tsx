import { AgentMessage } from "@/components/agent-message";
import { ExternalLinkIcon, XIcon } from "@/components/icons";
import type { CanonicalComparison, Listing } from "@/types/search";

function valueOrUnknown(value: string | number | undefined, suffix = "") {
  return value === undefined ? "Unknown" : `${value}${suffix}`;
}

function yesNoUnknown(value: unknown) {
  return value === true ? "Yes" : value === false ? "No" : "Unknown";
}

function evidenceAwareYesNo(value: unknown, queryBacked: boolean) {
  return queryBacked ? "Needs verification" : yesNoUnknown(value);
}

function fieldLabel(path: string) {
  const labels: Record<string, string> = {
    "property.bathrooms": "Bathroom count",
    "policies.petsAllowed": "Pet policy",
    "policies.parkingAvailable": "Parking availability",
    "media.primaryImageUrl": "Listing photo",
  };
  if (labels[path]) return labels[path];

  const fieldName = path.split(".").at(-1) ?? path;
  const words = fieldName
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .replace(/\burl\b/g, "URL")
    .replace(/\bid\b/g, "ID");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function statusLabel(status: string | undefined) {
  if (status === "pass") return "Passes confirmed requirements";
  if (status === "fail") return "Fails a confirmed requirement";
  if (status === "evidence_only") return "Needs stronger verification";
  return "Unknown";
}

function evidenceLabel(value: Record<string, unknown>) {
  const preference =
    typeof value.preference === "string" ? value.preference : "Preference";
  const rawStatus = typeof value.status === "string" ? value.status : "unknown";
  if (["in-unit laundry", "in unit laundry"].includes(preference.toLowerCase())) {
    const status =
      rawStatus === "supported"
        ? "Yes"
        : rawStatus === "evidence_only"
          ? "Needs verification"
          : rawStatus === "contradicted"
            ? "No"
            : "Unknown";
    return `In-unit laundry / washer-dryer: ${status}`;
  }
  const status = rawStatus.replaceAll("_", " ");
  return `${preference}: ${status}`;
}

function tradeoffLabel(value: string | Record<string, unknown>) {
  if (typeof value === "string") return value;
  for (const key of ["message", "description", "label"]) {
    if (typeof value[key] === "string") return value[key];
  }
  return "Structured trade-off recorded";
}

export function ComparisonPanel({
  listings,
  comparison,
  explanation,
  loading,
  error,
  onClose,
}: {
  listings: Listing[];
  comparison?: CanonicalComparison;
  explanation?: string;
  loading?: boolean;
  error?: string;
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

      {loading ? (
        <p className="comparisonNotice">
          Checking evidence and preparing the comparison…
        </p>
      ) : null}
      {error ? (
        <p className="comparisonNotice comparisonError" role="alert">
          {error}
        </p>
      ) : null}
      {explanation ? (
        <div className="comparisonExplanation">
          <strong>Agent explanation</strong>
          <AgentMessage>{explanation}</AgentMessage>
        </div>
      ) : null}

      <div className="comparisonGrid">
        {listings.map((listing, index) => {
          const result = comparison?.results.find(
            (item) => item.listingId === listing.id,
          );
          const policies = listing.canonicalListing?.policies;
          const queryBackedFields =
            listing.canonicalListing?.evidence.queryBackedFields ?? [];
          return (
            <article className="comparisonColumn" key={listing.id}>
            <span className="rank">Option {index + 1}</span>
            <h3>{listing.title ?? listing.address ?? "Rental home"}</h3>
            <dl>
              <div>
                <dt>Monthly rent</dt>
                <dd>
                  {listing.price === undefined
                    ? "Unknown"
                    : `$${Math.round(listing.price).toLocaleString()}`}
                </dd>
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
                <dt>Pets allowed</dt>
                <dd>
                  {evidenceAwareYesNo(
                    policies?.petsAllowed,
                    queryBackedFields.includes("policies.petsAllowed"),
                  )}
                </dd>
              </div>
              <div>
                <dt>Parking available</dt>
                <dd>
                  {evidenceAwareYesNo(
                    policies?.parkingAvailable,
                    queryBackedFields.includes("policies.parkingAvailable"),
                  )}
                </dd>
              </div>
              <div>
                <dt>Hard requirements</dt>
                <dd>{statusLabel(result?.hardConstraintStatus)}</dd>
              </div>
              <div>
                <dt>Decision ready</dt>
                <dd>
                  {result
                    ? result.decisionReady
                      ? "Yes"
                      : "No"
                    : "Unknown"}
                </dd>
              </div>
            </dl>
            {result?.softPreferenceEvidence.length ? (
              <div className="comparisonEvidence">
                <strong>Preference evidence</strong>
                <ul>
                  {result.softPreferenceEvidence.map((item, itemIndex) => (
                    <li key={`${listing.id}-evidence-${itemIndex}`}>
                      {evidenceLabel(item)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {result?.tradeoffs.length ? (
              <div className="comparisonEvidence">
                <strong>Trade-offs</strong>
                <ul>
                  {result.tradeoffs.map((item, itemIndex) => (
                    <li key={`${listing.id}-tradeoff-${itemIndex}`}>
                      {tradeoffLabel(item)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {result?.comparisonUnknowns.length ? (
              <div className="comparisonEvidence comparisonUnknowns">
                <strong>Still unknown or needs verification</strong>
                <ul>
                  {result.comparisonUnknowns.map((item) => (
                    <li key={item}>{fieldLabel(item)}</li>
                  ))}
                </ul>
              </div>
            ) : null}
            {listing.url ? (
              <a
                className="sourceLink"
                href={listing.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                View source <ExternalLinkIcon className="buttonIcon" />
              </a>
            ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
