"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { AgentMessage } from "@/components/agent-message";
import { Brand } from "@/components/brand";
import { ComparisonPanel } from "@/components/comparison-panel";
import {
  CheckIcon,
  HeartIcon,
  PlusIcon,
  SearchIcon,
} from "@/components/icons";
import { ListingCard } from "@/components/listing-card";
import { SearchComposer } from "@/components/search-composer";
import {
  getShortlist,
  removeShortlistItem,
  saveShortlistItem,
  sendChat,
} from "@/lib/api";
import type { AgentMode, Listing } from "@/types/search";

const examplePrompts = [
  "2 bed under $4,000 in Mountain View with parking",
  "Quiet cat-friendly apartment near Caltrain",
  "Modern 1 bed in Sunnyvale, flexible on move-in",
];

interface Turn {
  id: string;
  role: "user" | "agent";
  text: string;
}

function turnId(role: Turn["role"]) {
  return `${role}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function RentalSearch() {
  const [draft, setDraft] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [listings, setListings] = useState<Listing[]>([]);
  const [savedListings, setSavedListings] = useState<Listing[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showComparison, setShowComparison] = useState(false);
  const [mode, setMode] = useState<AgentMode>();
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [loading, setLoading] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getShortlist({ signal: controller.signal })
      .then((response) => {
        setSavedListings(response.items.map((item) => item.listing));
      })
      .catch((caught) => {
        if (caught instanceof Error && caught.name === "AbortError") return;
        setNotice("Your saved shortlist could not be loaded yet.");
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => requestRef.current?.abort(), []);

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(undefined), 4000);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = draft.trim();
    if (!message || loading) return;

    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    setTurns((current) => [...current, { id: turnId("user"), role: "user", text: message }]);
    setDraft("");
    setLoading(true);
    setError(undefined);
    setNotice(undefined);

    try {
      const response = await sendChat(
        { message, conversationId },
        { signal: controller.signal },
      );
      setConversationId(response.conversationId);
      setMode(response.mode);
      setListings(response.listings);
      setCompareIds([]);
      setShowComparison(false);
      setTurns((current) => [
        ...current,
        { id: turnId("agent"), role: "agent", text: response.message },
      ]);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setDraft(message);
      setError(caught instanceof Error ? caught.message : "The search could not be completed.");
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      setLoading(false);
    }
  }

  function applyPrompt(prompt: string) {
    setDraft(prompt);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function startNewSearch() {
    requestRef.current?.abort();
    setConversationId(undefined);
    setTurns([]);
    setListings([]);
    setCompareIds([]);
    setShowComparison(false);
    setMode(undefined);
    setError(undefined);
    setNotice("New search ready.");
    setDraft("");
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  async function toggleSaved(listing: Listing) {
    const isSaved = savedListings.some((item) => item.id === listing.id);
    if (isSaved) {
      const previous = savedListings;
      setSavedListings((current) => current.filter((item) => item.id !== listing.id));
      try {
        await removeShortlistItem(listing.id);
        setNotice("Removed from your shortlist.");
      } catch (caught) {
        setSavedListings(previous);
        setNotice(caught instanceof Error ? caught.message : "The home could not be removed.");
      }
      return;
    }

    if (!conversationId) {
      setNotice("Start a rental search before saving a home.");
      return;
    }

    setSavedListings((current) => [listing, ...current].slice(0, 24));
    try {
      const saved = await saveShortlistItem(listing.id, conversationId);
      setSavedListings((current) => [
        saved.listing,
        ...current.filter((item) => item.id !== saved.listing.id),
      ].slice(0, 24));
      setNotice("Saved to your shortlist.");
    } catch (caught) {
      setSavedListings((current) => current.filter((item) => item.id !== listing.id));
      setNotice(caught instanceof Error ? caught.message : "The home could not be saved.");
    }
  }

  function toggleComparison(listing: Listing) {
    if (compareIds.includes(listing.id)) {
      setCompareIds((current) => current.filter((id) => id !== listing.id));
      setShowComparison(false);
      setNotice("Removed from comparison.");
      return;
    }
    if (compareIds.length >= 3) {
      setNotice("Compare up to three homes at a time.");
      return;
    }
    setCompareIds((current) => [...current, listing.id]);
    setNotice("Added to comparison.");
  }

  const savedIds = new Set(savedListings.map((listing) => listing.id));
  const knownListings = new Map(
    [...savedListings, ...listings].map((listing) => [listing.id, listing]),
  );
  const comparisonListings = compareIds.flatMap((id) => {
    const listing = knownListings.get(id);
    return listing ? [listing] : [];
  });
  const journeyStage =
    turns.length === 0 ? 0 : listings.length === 0 ? 0 : compareIds.length < 2 ? 1 : showComparison ? 3 : 2;

  return (
    <div className="appShell">
      <a className="skipLink" href="#main-content">Skip to rental search</a>
      <header className="topbar">
        <Brand />
        <div className="topbarActions">
          <span className="agentStatus"><span />Agent ready</span>
          {turns.length ? (
            <button className="quietButton" type="button" onClick={startNewSearch}>
              <PlusIcon className="buttonIcon" /> New search
            </button>
          ) : null}
        </div>
      </header>

      <div className="workspace">
        <main className="mainPanel" id="main-content">
          {turns.length === 0 ? (
            <section className="welcome" aria-labelledby="page-title">
              <span className="heroEyebrow">Bay Area rentals · Agentic search</span>
              <h1 id="page-title">A better rental,<br />without the tab chaos.</h1>
              <p>
                Tell us what matters once. Your agent searches, checks hard constraints,
                and explains the trade-offs so you can decide with confidence.
              </p>
              <SearchComposer
                compareCount={compareIds.length}
                draft={draft}
                error={error}
                hasConversation={false}
                loading={loading}
                onDraftChange={setDraft}
                onShowComparison={() => setShowComparison(true)}
                onSubmit={submit}
                textareaRef={textareaRef}
                welcome
              />
              <div className="promptList" aria-label="Example rental searches">
                {examplePrompts.map((prompt) => (
                  <button type="button" key={prompt} onClick={() => applyPrompt(prompt)}>
                    <SearchIcon />
                    <span>{prompt}</span>
                  </button>
                ))}
              </div>
            </section>
          ) : (
            <section className="conversation" aria-label="Rental search conversation" aria-busy={loading}>
              <header className="conversationHeader">
                <div>
                  <span className="sectionEyebrow">Your search</span>
                  <h1>Let’s narrow it down.</h1>
                </div>
                {mode ? <span className="modeBadge">{mode === "adk" ? "Live agent" : "Development mode"}</span> : null}
              </header>

              <div className="thread">
                {turns.map((turn) => (
                  <article className={`turn ${turn.role}`} key={turn.id}>
                    <span>{turn.role === "user" ? "You" : "Keys"}</span>
                    {turn.role === "agent" ? (
                      <AgentMessage>{turn.text}</AgentMessage>
                    ) : (
                      <p>{turn.text}</p>
                    )}
                  </article>
                ))}
                {loading ? (
                  <article className="turn agent loadingTurn">
                    <span>Keys</span>
                    <div className="loadingMessage">
                      <span className="loadingDots" aria-hidden="true"><i /><i /><i /></span>
                      <p>Checking available homes and verifying the important details…</p>
                    </div>
                  </article>
                ) : null}
              </div>

              {!loading && listings.length ? (
                <section className="resultsSection" aria-labelledby="results-title">
                  <div className="sectionHeading">
                    <div>
                      <span className="sectionEyebrow">Ranked for your request</span>
                      <h2 id="results-title">The strongest matches</h2>
                    </div>
                    <p>{listings.length} {listings.length === 1 ? "home" : "homes"}</p>
                  </div>
                  <div className="listingGrid">
                    {listings.map((listing, index) => (
                      <ListingCard
                        listing={listing}
                        rank={listing.rank ?? index + 1}
                        saved={savedIds.has(listing.id)}
                        selected={compareIds.includes(listing.id)}
                        onSave={toggleSaved}
                        onSelect={toggleComparison}
                        key={listing.id}
                      />
                    ))}
                  </div>
                </section>
              ) : null}

              {showComparison && comparisonListings.length >= 2 ? (
                <ComparisonPanel listings={comparisonListings} onClose={() => setShowComparison(false)} />
              ) : null}
            </section>
          )}
          {turns.length ? (
            <SearchComposer
              compareCount={compareIds.length}
              draft={draft}
              error={error}
              hasConversation={Boolean(conversationId)}
              loading={loading}
              onDraftChange={setDraft}
              onShowComparison={() => setShowComparison(true)}
              onSubmit={submit}
              textareaRef={textareaRef}
            />
          ) : null}
        </main>

        <aside className="decisionRail" aria-label="Rental decision progress">
          <section className="railCard journeyCard">
            <span className="sectionEyebrow">Decision path</span>
            <h2>From search to keys</h2>
            <ol className="journeyList">
              {["Find", "Verify", "Compare", "Decide"].map((step, index) => (
                <li className={index < journeyStage ? "isDone" : index === journeyStage ? "isCurrent" : ""} key={step}>
                  <span>{index < journeyStage ? <CheckIcon /> : index + 1}</span>
                  <div><strong>{step}</strong><small>{["Tell us what matters", "Check facts and unknowns", "See trade-offs side by side", "Keep the right shortlist"][index]}</small></div>
                </li>
              ))}
            </ol>
          </section>

          <section className="railCard shortlistCard">
            <div className="railCardHeading">
              <div>
                <span className="sectionEyebrow">Shortlist</span>
                <h2>{savedListings.length ? `${savedListings.length} saved` : "Nothing saved yet"}</h2>
              </div>
              <HeartIcon className="railIcon" fill={savedListings.length ? "currentColor" : "none"} />
            </div>
            {savedListings.length ? (
              <ul className="savedList">
                {savedListings.slice(0, 3).map((listing) => (
                  <li key={listing.id}>
                    <span>{listing.title ?? listing.address ?? "Rental home"}</span>
                    <strong>{listing.price === undefined ? "Price unknown" : `$${Math.round(listing.price).toLocaleString()}`}</strong>
                  </li>
                ))}
              </ul>
            ) : (
              <p>Save promising homes here. Your shortlist is stored by the backend.</p>
            )}
          </section>

          <section className="trustNote">
            <CheckIcon />
            <p><strong>You stay in control.</strong> Unknowns stay unknown, and no landlord is contacted without approval.</p>
          </section>
        </aside>
      </div>

      {notice ? <div className="statusToast" role="status" aria-live="polite">{notice}</div> : null}
    </div>
  );
}
