"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import type { User } from "firebase/auth";

import { AgentMessage } from "@/components/agent-message";
import { Brand } from "@/components/brand";
import { ComparisonPanel } from "@/components/comparison-panel";
import {
  CheckIcon,
  EyeIcon,
  EyeOffIcon,
  HeartIcon,
  ListIcon,
  MapIcon,
  PlusIcon,
  SearchIcon,
} from "@/components/icons";
import { ListingCard } from "@/components/listing-card";
import { RecentSearches } from "@/components/recent-searches";
import { RentalMap } from "@/components/rental-map";
import { SearchComposer } from "@/components/search-composer";
import { useRecentSearches } from "@/hooks/use-recent-searches";
import { useRouteSelection } from "@/hooks/use-route-selection";
import {
  compareListings,
  getShortlist,
  removeShortlistItem,
  saveShortlistItem,
  sendChat,
} from "@/lib/api";
import {
  createAccountWithEmail,
  getAuthIdentityKey,
  observeFirebaseUser,
  signInWithEmail,
  signInWithGoogle,
  signOutToAnonymous,
} from "@/lib/firebase-auth";
import type {
  AgentMode,
  CanonicalComparison,
  CommuteEvaluation,
  Listing,
  RecentSearch,
  SearchRequirements,
} from "@/types/search";

const examplePrompts = [
  "2 bed under $4,000 in Mountain View with parking",
  "Quiet cat-friendly apartment near Caltrain",
  "Modern 1 bed in Sunnyvale, flexible on move-in",
];

const guidedRequirementSteps: Record<string, { question: string; options: { label: string; message: string }[] }> = {
  commute_destination: {
    question: "Where do you commute to?",
    options: [
      { label: "Google Mountain View", message: "My commute destination is Google Mountain View." },
      { label: "Apple Park", message: "My commute destination is Apple Park." },
      { label: "Meta Menlo Park", message: "My commute destination is Meta Menlo Park." },
    ],
  },
  commute_travel_mode: {
    question: "How do you usually commute?",
    options: [
      { label: "Drive", message: "My commute travel mode is DRIVE." },
      { label: "Transit", message: "My commute travel mode is TRANSIT." },
      { label: "Bike", message: "My commute travel mode is BICYCLE." },
      { label: "Walk", message: "My commute travel mode is WALK." },
    ],
  },
};

function requirementLabels(requirements?: SearchRequirements) {
  if (!requirements) return [];
  const labels: string[] = [];
  if (requirements.city) labels.push(`${requirements.city}${requirements.state ? `, ${requirements.state}` : ""}`);
  if (requirements.maxRent !== undefined) labels.push(`≤ $${requirements.maxRent.toLocaleString()}/mo`);
  if (requirements.minBedrooms !== undefined) labels.push(`${requirements.minBedrooms}+ bed`);
  if (requirements.minBathrooms !== undefined) labels.push(`${requirements.minBathrooms}+ bath`);
  if (requirements.petsRequired) labels.push("Pet-friendly");
  if (requirements.parkingRequired) labels.push("Parking required");
  if (requirements.maxCommuteMinutes !== undefined) labels.push(`≤ ${requirements.maxCommuteMinutes} min commute`);
  if (requirements.commuteDestination) labels.push(`to ${requirements.commuteDestination}`);
  if (requirements.commuteTravelMode) labels.push(requirements.commuteTravelMode.toLowerCase());
  labels.push(...requirements.softPreferences);
  return labels;
}

interface Turn {
  id: string;
  role: "user" | "agent";
  text: string;
}

function turnId(role: Turn["role"]) {
  return `${role}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function recentSearchDate(timestamp: string) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "an earlier date";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(date);
}

function useMobileViewport() {
  const [isMobileViewport, setIsMobileViewport] = useState<boolean>();

  useEffect(() => {
    if (!window.matchMedia) {
      setIsMobileViewport(false);
      return;
    }

    const mediaQuery = window.matchMedia("(max-width: 900px)");
    const updateViewport = () => setIsMobileViewport(mediaQuery.matches);
    updateViewport();
    mediaQuery.addEventListener("change", updateViewport);
    return () => mediaQuery.removeEventListener("change", updateViewport);
  }, []);

  return isMobileViewport;
}

export function RentalSearch() {
  const [draft, setDraft] = useState("");
  const [conversationId, setConversationId] = useState<string>();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [listings, setListings] = useState<Listing[]>([]);
  const [requirements, setRequirements] = useState<SearchRequirements>();
  const [missingRequirements, setMissingRequirements] = useState<string[]>([]);
  const [commuteEvaluation, setCommuteEvaluation] = useState<CommuteEvaluation>();
  const [mobileResultsView, setMobileResultsView] = useState<"list" | "map">("list");
  const [highlightedListingId, setHighlightedListingId] = useState<string>();
  const [savedListings, setSavedListings] = useState<Listing[]>([]);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showComparison, setShowComparison] = useState(false);
  const [comparison, setComparison] = useState<CanonicalComparison>();
  const [comparisonExplanation, setComparisonExplanation] = useState<string>();
  const [comparisonError, setComparisonError] = useState<string>();
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [mode, setMode] = useState<AgentMode>();
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [restoredSearchNotice, setRestoredSearchNotice] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [authUser, setAuthUser] = useState<User | null>();
  const [authBusy, setAuthBusy] = useState(false);
  const [authDialogOpen, setAuthDialogOpen] = useState(false);
  const [authView, setAuthView] = useState<"sign-in" | "create">("sign-in");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authPasswordVisible, setAuthPasswordVisible] = useState(false);
  const [authFormError, setAuthFormError] = useState<string>();
  const [authFormStatus, setAuthFormStatus] = useState<string>();
  const requestRef = useRef<AbortController | null>(null);
  const comparisonRequestRef = useRef<AbortController | null>(null);
  const shortlistRequestRef = useRef<AbortController | null>(null);
  const activeFirebaseUidRef = useRef<string | undefined>(undefined);
  const identityGenerationRef = useRef(0);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const routeSelection = useRouteSelection(conversationId);
  const recentSearches = useRecentSearches(authUser);
  const isMobileViewport = useMobileViewport();
  const mapVisible = isMobileViewport === false || (isMobileViewport === true && mobileResultsView === "map");
  const authIdentityKey = getAuthIdentityKey(authUser);

  function isCurrentIdentity(generation: number) {
    return identityGenerationRef.current === generation;
  }

  function abortChatRequest() {
    requestRef.current?.abort();
    requestRef.current = null;
  }

  function resetForFirebaseBoundary(nextUid?: string) {
    abortChatRequest();
    comparisonRequestRef.current?.abort();
    comparisonRequestRef.current = null;
    shortlistRequestRef.current?.abort();
    shortlistRequestRef.current = null;
    routeSelection.reset();
    activeFirebaseUidRef.current = nextUid;
    identityGenerationRef.current += 1;
    setDraft("");
    setConversationId(undefined);
    setTurns([]);
    setListings([]);
    setRequirements(undefined);
    setMissingRequirements([]);
    setCommuteEvaluation(undefined);
    setMobileResultsView("list");
    setHighlightedListingId(undefined);
    setSavedListings([]);
    setCompareIds([]);
    setShowComparison(false);
    setComparison(undefined);
    setComparisonExplanation(undefined);
    setComparisonError(undefined);
    setComparisonLoading(false);
    setMode(undefined);
    setError(undefined);
    setNotice(undefined);
    setRestoredSearchNotice(undefined);
    setLoading(false);
  }

  useEffect(() => observeFirebaseUser(setAuthUser), []);

  useEffect(() => {
    const uid = authIdentityKey;
    const previousUid = activeFirebaseUidRef.current;

    if (!uid) {
      if (previousUid !== undefined) resetForFirebaseBoundary();
      return;
    }

    if (previousUid !== undefined && previousUid !== uid) {
      resetForFirebaseBoundary(uid);
    } else {
      activeFirebaseUidRef.current = uid;
    }

    const identityGeneration = identityGenerationRef.current;
    const controller = new AbortController();
    shortlistRequestRef.current?.abort();
    shortlistRequestRef.current = controller;
    getShortlist({ signal: controller.signal })
      .then((response) => {
        if (
          shortlistRequestRef.current !== controller
          || activeFirebaseUidRef.current !== uid
          || !isCurrentIdentity(identityGeneration)
        ) return;
        setSavedListings(response.items.map((item) => item.listing));
      })
      .catch((caught) => {
        if (
          caught instanceof Error && caught.name === "AbortError"
          || shortlistRequestRef.current !== controller
          || activeFirebaseUidRef.current !== uid
          || !isCurrentIdentity(identityGeneration)
        ) return;
        setNotice("Your saved shortlist could not be loaded yet.");
      });
    return () => {
      controller.abort();
      if (shortlistRequestRef.current === controller) shortlistRequestRef.current = null;
    };
  }, [authIdentityKey]);

  useEffect(() => () => {
    abortChatRequest();
    comparisonRequestRef.current?.abort();
    shortlistRequestRef.current?.abort();
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timeout = window.setTimeout(() => setNotice(undefined), 4000);
    return () => window.clearTimeout(timeout);
  }, [notice]);

  useEffect(() => {
    if (!authDialogOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setAuthDialogOpen(false);
      setAuthFormError(undefined);
      setAuthFormStatus(undefined);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [authDialogOpen]);

  async function submitMessage(rawMessage: string) {
    const message = rawMessage.trim();
    if (!message || loading) return;

    const identityGeneration = identityGenerationRef.current;
    const controller = new AbortController();
    abortChatRequest();
    comparisonRequestRef.current?.abort();
    routeSelection.reset();
    setHighlightedListingId(undefined);
    requestRef.current = controller;
    setTurns((current) => [...current, { id: turnId("user"), role: "user", text: message }]);
    setDraft("");
    setLoading(true);
    setError(undefined);
    setNotice(undefined);
    setRestoredSearchNotice(undefined);

    try {
      const response = await sendChat(
        { message, conversationId },
        { signal: controller.signal },
      );
      if (requestRef.current !== controller || !isCurrentIdentity(identityGeneration)) return;
      setConversationId(response.conversationId);
      setMode(response.mode);
      setListings(response.listings);
      setRequirements(response.requirements);
      setMissingRequirements(response.missingRequirements ?? []);
      setCommuteEvaluation(response.commuteEvaluation);
      routeSelection.reset();
      setMobileResultsView("list");
      setHighlightedListingId(undefined);
      setCompareIds([]);
      setShowComparison(false);
      setComparison(undefined);
      setComparisonExplanation(undefined);
      setComparisonError(undefined);
      setComparisonLoading(false);
      setTurns((current) => [
        ...current,
        { id: turnId("agent"), role: "agent", text: response.message },
      ]);
      void recentSearches.refresh();
    } catch (caught) {
      if (requestRef.current !== controller || !isCurrentIdentity(identityGeneration)) return;
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setDraft(message);
      setError(caught instanceof Error ? caught.message : "The search could not be completed.");
    } finally {
      if (requestRef.current !== controller) return;
      requestRef.current = null;
      setLoading(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitMessage(draft);
  }

  function applyPrompt(prompt: string) {
    setDraft(prompt);
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function openAuthDialog() {
    setAuthView("sign-in");
    setAuthFormError(undefined);
    setAuthFormStatus(undefined);
    setAuthPasswordVisible(false);
    setAuthDialogOpen(true);
  }

  function closeAuthDialog() {
    setAuthDialogOpen(false);
    setAuthFormError(undefined);
    setAuthFormStatus(undefined);
    setAuthPassword("");
    setAuthPasswordVisible(false);
  }

  function switchAuthView(view: "sign-in" | "create") {
    setAuthView(view);
    setAuthFormError(undefined);
    setAuthFormStatus(undefined);
    setAuthPassword("");
    setAuthPasswordVisible(false);
  }

  async function handleGoogleSignIn() {
    if (authBusy) return;
    setAuthBusy(true);
    setAuthFormError(undefined);
    setAuthFormStatus(undefined);
    try {
      setAuthUser(await signInWithGoogle());
      closeAuthDialog();
    } catch (caught) {
      setAuthFormError(caught instanceof Error ? caught.message : "Google sign-in could not be completed.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleEmailAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (authBusy) return;

    const email = authEmail.trim();
    if (!email) {
      setAuthFormError("Enter your email address.");
      return;
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setAuthFormError("Enter a valid email address.");
      return;
    }
    if (authPassword.length < 6) {
      setAuthFormError("Use at least 6 characters for your password.");
      return;
    }

    setAuthBusy(true);
    setAuthFormError(undefined);
    setAuthFormStatus(undefined);
    try {
      const user = authView === "create"
        ? await createAccountWithEmail(email, authPassword)
        : await signInWithEmail(email, authPassword);
      setAuthUser(user);
      closeAuthDialog();
    } catch (caught) {
      setAuthFormError(caught instanceof Error ? caught.message : "Email sign-in could not be completed.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function handleSignOut() {
    if (authBusy) return;
    setAuthBusy(true);
    setNotice(undefined);
    try {
      setAuthUser(await signOutToAnonymous());
    } catch (caught) {
      setNotice(caught instanceof Error ? caught.message : "Sign out could not be completed.");
    } finally {
      setAuthBusy(false);
    }
  }

  function startNewSearch() {
    abortChatRequest();
    comparisonRequestRef.current?.abort();
    setConversationId(undefined);
    setTurns([]);
    setListings([]);
    setRequirements(undefined);
    setMissingRequirements([]);
    setCommuteEvaluation(undefined);
    routeSelection.reset();
    setMobileResultsView("list");
    setHighlightedListingId(undefined);
    setCompareIds([]);
    setShowComparison(false);
    setComparison(undefined);
    setComparisonExplanation(undefined);
    setComparisonError(undefined);
    setComparisonLoading(false);
    setMode(undefined);
    setError(undefined);
    setNotice("New search ready.");
    setRestoredSearchNotice(undefined);
    setDraft("");
    requestAnimationFrame(() => textareaRef.current?.focus());
  }

  function restoreRecentSearch(search: RecentSearch, continueSearch: boolean) {
    abortChatRequest();
    comparisonRequestRef.current?.abort();
    comparisonRequestRef.current = null;
    routeSelection.reset();
    setDraft("");
    setConversationId(search.conversationId);
    setTurns([]);
    setListings(search.listings);
    setRequirements(undefined);
    setMissingRequirements([]);
    setCommuteEvaluation(undefined);
    setMobileResultsView("list");
    setHighlightedListingId(undefined);
    setCompareIds([]);
    setShowComparison(false);
    setComparison(undefined);
    setComparisonExplanation(undefined);
    setComparisonError(undefined);
    setComparisonLoading(false);
    setMode(undefined);
    setError(undefined);
    setNotice(undefined);
    setRestoredSearchNotice(
      `${continueSearch ? "Continuing your search" : "Showing the latest saved results"} from ${recentSearchDate(search.updatedAt)}.`,
    );
    setLoading(false);
    if (continueSearch) requestAnimationFrame(() => textareaRef.current?.focus());
  }

  async function toggleSaved(listing: Listing) {
    const identityGeneration = identityGenerationRef.current;
    const isSaved = savedListings.some((item) => item.id === listing.id);
    if (isSaved) {
      const previous = savedListings;
      setSavedListings((current) => current.filter((item) => item.id !== listing.id));
      try {
        await removeShortlistItem(listing.id);
        if (!isCurrentIdentity(identityGeneration)) return;
        setNotice("Removed from your shortlist.");
      } catch (caught) {
        if (!isCurrentIdentity(identityGeneration)) return;
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
      if (!isCurrentIdentity(identityGeneration)) return;
      setSavedListings((current) => [
        saved.listing,
        ...current.filter((item) => item.id !== saved.listing.id),
      ].slice(0, 24));
      setNotice("Saved to your shortlist.");
    } catch (caught) {
      if (!isCurrentIdentity(identityGeneration)) return;
      setSavedListings((current) => current.filter((item) => item.id !== listing.id));
      setNotice(caught instanceof Error ? caught.message : "The home could not be saved.");
    }
  }

  function toggleComparison(listing: Listing) {
    comparisonRequestRef.current?.abort();
    setComparison(undefined);
    setComparisonExplanation(undefined);
    setComparisonError(undefined);
    setComparisonLoading(false);
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

  async function openComparison() {
    if (!conversationId || compareIds.length < 2) return;
    const identityGeneration = identityGenerationRef.current;
    const controller = new AbortController();
    comparisonRequestRef.current?.abort();
    comparisonRequestRef.current = controller;
    setShowComparison(true);
    setComparisonLoading(true);
    setComparisonError(undefined);
    try {
      const response = await compareListings(compareIds, conversationId, {
        signal: controller.signal,
      });
      if (comparisonRequestRef.current !== controller || !isCurrentIdentity(identityGeneration)) return;
      const refreshedById = new Map(
        response.listings.map((listing) => [listing.id, listing]),
      );
      setListings((current) =>
        current.map((listing) => refreshedById.get(listing.id) ?? listing),
      );
      setComparison(response.comparison);
      setComparisonExplanation(response.message);
    } catch (caught) {
      if (comparisonRequestRef.current !== controller || !isCurrentIdentity(identityGeneration)) return;
      if (caught instanceof Error && caught.name === "AbortError") return;
      setComparisonError(
        caught instanceof Error
          ? caught.message
          : "The comparison could not be prepared.",
      );
    } finally {
      if (comparisonRequestRef.current === controller) {
        comparisonRequestRef.current = null;
        setComparisonLoading(false);
      }
    }
  }

  const selectOnMap = useCallback((listing: Listing) => {
    setHighlightedListingId(undefined);
    setMobileResultsView("map");
    void routeSelection.selectListing(listing);
  }, [routeSelection.selectListing]);

  const highlightOnMap = useCallback((listingId?: string) => {
    setHighlightedListingId(listingId);
  }, []);

  const savedIds = new Set(savedListings.map((listing) => listing.id));
  const knownListings = new Map(
    [...savedListings, ...listings].map((listing) => [listing.id, listing]),
  );
  const comparisonListings = compareIds.flatMap((id) => {
    const listing = knownListings.get(id);
    return listing ? [listing] : [];
  });
  const hasActiveSearch = Boolean(conversationId) || turns.length > 0 || listings.length > 0;
  const guidedRequirement = missingRequirements
    .map((name) => guidedRequirementSteps[name])
    .find((step) => step !== undefined);
  const activeRequirementLabels = requirementLabels(requirements);
  const journeyStage =
    listings.length === 0 ? 0 : turns.length === 0 ? 1 : compareIds.length < 2 ? 1 : showComparison ? 3 : 2;

  return (
    <div className="appShell">
      <a className="skipLink" href="#main-content">Skip to rental search</a>
      <header className="topbar">
        <Brand />
        <div className="topbarActions">
          <span className="agentStatus"><span />Agent ready</span>
          {authUser?.isAnonymous ? (
            <button
              className="authButton signInButton"
              type="button"
              onClick={openAuthDialog}
              disabled={authBusy}
            >
              Sign in
            </button>
          ) : authUser ? (
            <div className="accountControls">
              <div className="accountIdentity">
                {authUser.displayName ? <strong>{authUser.displayName}</strong> : null}
                {authUser.email ? <span>{authUser.email}</span> : <span>Google account</span>}
              </div>
              <button
                className="authButton"
                type="button"
                onClick={handleSignOut}
                disabled={authBusy}
              >
                {authBusy ? "Signing out…" : "Sign Out"}
              </button>
            </div>
          ) : null}
          {hasActiveSearch ? (
            <button className="quietButton" type="button" onClick={startNewSearch}>
              <PlusIcon className="buttonIcon" /> New search
            </button>
          ) : null}
        </div>
      </header>

      {authUser?.isAnonymous && authDialogOpen ? (
        <div
          className="authModalBackdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeAuthDialog();
          }}
        >
          <section
            className="authDialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="auth-dialog-title"
          >
            <button
              className="authDialogClose"
              type="button"
              aria-label="Close sign in dialog"
              onClick={closeAuthDialog}
            >
              ×
            </button>
            <div className="authDialogHeader">
              <span className="sectionEyebrow">Your Keys account</span>
              <h2 id="auth-dialog-title">
                {authView === "create" ? "Create your account" : "Sign in to Keys by Friday"}
              </h2>
              <p>
                {authView === "create"
                  ? "Keep your shortlist and rental search connected across sessions."
                  : "Pick up your shortlist and rental search wherever you left off."}
              </p>
            </div>

            <form className="authForm" noValidate onSubmit={handleEmailAuth}>
              <label>
                <span>Email address</span>
                <input
                  type="email"
                  value={authEmail}
                  onChange={(event) => setAuthEmail(event.target.value)}
                  autoComplete="email"
                  autoFocus
                />
              </label>
              <div className="authField">
                <div className="authPasswordLabel">
                  <label htmlFor="auth-password">Password</label>
                  {authView === "sign-in" ? (
                    <button
                      className="authTextButton"
                      type="button"
                      onClick={() => {
                        setAuthFormError(undefined);
                        setAuthFormStatus("Password reset is coming soon.");
                      }}
                    >
                      Forgot password?
                    </button>
                  ) : null}
                </div>
                <div className="authPasswordInput">
                  <input
                    id="auth-password"
                    type={authPasswordVisible ? "text" : "password"}
                    value={authPassword}
                    onChange={(event) => setAuthPassword(event.target.value)}
                    autoComplete={authView === "create" ? "new-password" : "current-password"}
                  />
                  <button
                    className="authPasswordToggle"
                    type="button"
                    aria-label={authPasswordVisible ? "Hide password" : "Show password"}
                    aria-pressed={authPasswordVisible}
                    onClick={() => setAuthPasswordVisible((visible) => !visible)}
                  >
                    {authPasswordVisible ? <EyeOffIcon /> : <EyeIcon />}
                  </button>
                </div>
              </div>

              {authFormError ? <p className="authFormMessage error" role="alert">{authFormError}</p> : null}
              {authFormStatus ? <p className="authFormMessage" role="status">{authFormStatus}</p> : null}

              <button className="authPrimaryButton" type="submit" disabled={authBusy}>
                {authBusy
                  ? authView === "create" ? "Creating account…" : "Signing in…"
                  : authView === "create" ? "Create account" : "Sign in"}
              </button>
            </form>

            <div className="authDivider" aria-hidden="true"><span>or</span></div>

            <button
              className="googleAuthButton"
              type="button"
              onClick={handleGoogleSignIn}
              disabled={authBusy}
            >
              <span className="googleAuthMark" aria-hidden="true">G</span>
              {authBusy ? "Connecting…" : "Continue with Google"}
            </button>

            <p className="authDialogFooter">
              {authView === "create" ? "Already have an account?" : "Don’t have an account?"}
              <button
                className="authTextButton"
                type="button"
                onClick={() => switchAuthView(authView === "create" ? "sign-in" : "create")}
              >
                {authView === "create" ? "Sign in" : "Create account"}
              </button>
            </p>
          </section>
        </div>
      ) : null}

      <div className="workspace">
        <main className="mainPanel" id="main-content">
          {!hasActiveSearch ? (
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
                onShowComparison={() => void openComparison()}
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
            <>
              {listings.length > 0 ? (
                <div className="mobileResultsSwitch" role="group" aria-label="Rental results view">
                  <button type="button" aria-pressed={mobileResultsView === "list"} onClick={() => setMobileResultsView("list")}>
                    <ListIcon /> List
                  </button>
                  <button type="button" aria-pressed={mobileResultsView === "map"} onClick={() => setMobileResultsView("map")}>
                    <MapIcon /> Map
                  </button>
                </div>
              ) : null}
              <div
                className={listings.length > 0 ? "spatialWorkspace" : undefined}
                data-mobile-view={listings.length > 0 ? mobileResultsView : undefined}
              >
                <div className={listings.length > 0 ? "spatialListPane" : undefined}>
                  <section className="conversation" aria-label="Rental search conversation" aria-busy={loading}>
              <header className="conversationHeader">
                <div>
                  <span className="sectionEyebrow">Your search</span>
                  <h1>Let’s narrow it down.</h1>
                </div>
                {mode ? <span className="modeBadge">{mode === "adk" ? "Live agent" : "Development mode"}</span> : null}
              </header>

              {restoredSearchNotice ? (
                <p className="restoredSearchNotice" role="status">{restoredSearchNotice}</p>
              ) : null}

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

              {!loading && (activeRequirementLabels.length > 0 || guidedRequirement) ? (
                <section className="agentRequirements" aria-label="Current rental requirements">
                  {activeRequirementLabels.length > 0 ? (
                    <div className="requirementSnapshot">
                      <span>Agent remembers</span>
                      <div className="requirementChips">
                        {activeRequirementLabels.map((label) => <span key={label}>{label}</span>)}
                      </div>
                    </div>
                  ) : null}
                  {guidedRequirement ? (
                    <div className="guidedRequirement">
                      <strong>{guidedRequirement.question}</strong>
                      <div className="guidedRequirementOptions">
                        {guidedRequirement.options.map((option) => (
                          <button
                            type="button"
                            key={option.label}
                            onClick={() => void submitMessage(option.message)}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>
                      <span>Or type another answer below.</span>
                    </div>
                  ) : null}
                </section>
              ) : null}

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
                        comparisonSelected={compareIds.includes(listing.id)}
                        mapSelected={routeSelection.state.selectedListingId === listing.id}
                        mapHighlighted={highlightedListingId === listing.id}
                        onSave={toggleSaved}
                        onSelect={toggleComparison}
                        onMapSelect={selectOnMap}
                        onMapHighlight={highlightOnMap}
                        key={listing.id}
                      />
                    ))}
                  </div>
                </section>
              ) : null}

              {showComparison && comparisonListings.length >= 2 ? (
                <ComparisonPanel
                  listings={comparisonListings}
                  comparison={comparison}
                  explanation={comparisonExplanation}
                  loading={comparisonLoading}
                  error={comparisonError}
                  onClose={() => setShowComparison(false)}
                />
              ) : null}
                  </section>
                  <SearchComposer
                    compareCount={compareIds.length}
                    draft={draft}
                    error={error}
                    hasConversation={Boolean(conversationId)}
                    loading={loading}
                    onDraftChange={setDraft}
                    onShowComparison={() => void openComparison()}
                    onSubmit={submit}
                    textareaRef={textareaRef}
                  />
                </div>
                {listings.length > 0 ? (
                  <aside className="spatialMapPane" aria-label="Rental locations and commute routes">
                    <RentalMap
                      listings={listings}
                      commuteEvaluation={commuteEvaluation}
                      routeState={routeSelection.state}
                      highlightedListingId={highlightedListingId}
                      onSelectListing={selectOnMap}
                      onHighlightListing={highlightOnMap}
                      apiKey={process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY}
                      mapId={process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID}
                      mapVisible={mapVisible}
                    />
                  </aside>
                ) : null}
              </div>
            </>
          )}
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

          {authUser && !authUser.isAnonymous ? (
            <RecentSearches
              items={recentSearches.items}
              loading={recentSearches.loading}
              error={recentSearches.error}
              onRetry={recentSearches.refresh}
              onViewResults={(search) => restoreRecentSearch(search, false)}
              onContinueSearch={(search) => restoreRecentSearch(search, true)}
            />
          ) : null}

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
