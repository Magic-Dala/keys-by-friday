"use client";

import { FormEvent, useState } from "react";

import { ListingCard } from "@/components/listing-card";
import { sendChat } from "@/lib/api";
import type { SearchResponse } from "@/types/search";

const example = "2B2B under $4,000 in Mountain View";

export function RentalSearch() {
  const [message, setMessage] = useState(example);
  const [conversationId, setConversationId] = useState<string>();
  const [result, setResult] = useState<SearchResponse>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = message.trim();
    if (!trimmed || loading) return;

    setLoading(true);
    setError(undefined);
    try {
      const response = await sendChat({ message: trimmed, conversationId });
      setConversationId(response.conversationId);
      setResult(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed.");
    } finally {
      setLoading(false);
    }
  }

  function startNewSearch() {
    setConversationId(undefined);
    setResult(undefined);
    setError(undefined);
    setMessage(example);
  }

  return (
    <section className="card" aria-labelledby="page-title">
      <header className="header">
        <span className="eyebrow">AI Rental Agent</span>
        <h1 id="page-title">Keys by Friday</h1>
        <p>Describe the rental you want. The web app talks to the Agent through one API.</p>
      </header>

      <form onSubmit={submit} className="composer">
        <label htmlFor="message">Rental request</label>
        <textarea
          id="message"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={4}
          maxLength={4000}
          placeholder={example}
          disabled={loading}
        />
        <div className="formActions">
          <button type="submit" disabled={loading || !message.trim()}>
            {loading ? "Searching…" : conversationId ? "Refine search" : "Ask agent"}
          </button>
          {conversationId ? (
            <button className="secondaryButton" type="button" onClick={startNewSearch} disabled={loading}>
              New search
            </button>
          ) : null}
        </div>
      </form>

      <section className="output" aria-live="polite" aria-busy={loading}>
        <div className="outputHeader">
          <h2>Agent output</h2>
          {result ? <span className="mode">{result.mode}</span> : null}
        </div>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {!error && !result ? (
          <p className="muted">Start with a request, then refine it in the same conversation.</p>
        ) : null}
        {result ? <p className="response">{result.message}</p> : null}

        {result?.listings.length ? (
          <div className="listingGrid" aria-label="Rental results">
            {result.listings.map((listing) => (
              <ListingCard listing={listing} key={listing.id} />
            ))}
          </div>
        ) : null}
      </section>
    </section>
  );
}
