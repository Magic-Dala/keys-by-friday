import type { Listing } from "@/types/search";

export function ListingCard({ listing }: { listing: Listing }) {
  return (
    <article className="listingCard">
      <div className="listingHeading">
        <h3>{listing.title ?? listing.address ?? "Rental listing"}</h3>
        {listing.price !== undefined ? (
          <strong>${listing.price.toLocaleString()}/mo</strong>
        ) : null}
      </div>
      <p className="listingFacts">
        {listing.bedrooms !== undefined ? `${listing.bedrooms} bed` : "Beds unknown"}
        {" · "}
        {listing.bathrooms !== undefined ? `${listing.bathrooms} bath` : "Baths unknown"}
      </p>
      {listing.reason ? <p className="listingReason">{listing.reason}</p> : null}
      {listing.url ? (
        <a href={listing.url} target="_blank" rel="noopener noreferrer">
          View source
        </a>
      ) : null}
    </article>
  );
}
