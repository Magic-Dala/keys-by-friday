import type { FormEvent, RefObject } from "react";

import { ArrowUpIcon, CompareIcon } from "@/components/icons";

interface SearchComposerProps {
  compareCount: number;
  draft: string;
  error?: string;
  hasConversation: boolean;
  loading: boolean;
  onDraftChange: (value: string) => void;
  onShowComparison: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  welcome?: boolean;
}

export function SearchComposer({
  compareCount,
  draft,
  error,
  hasConversation,
  loading,
  onDraftChange,
  onShowComparison,
  onSubmit,
  textareaRef,
  welcome = false,
}: SearchComposerProps) {
  return (
    <div className={welcome ? "composerDock welcomeComposer" : "composerDock"}>
      {error ? <p className="composerError" role="alert">{error}</p> : null}
      {compareCount ? (
        <div className="compareBar">
          <span><CompareIcon /> {compareCount} selected</span>
          <button type="button" disabled={compareCount < 2} onClick={onShowComparison}>
            Compare homes
          </button>
        </div>
      ) : null}
      <form className="composer" onSubmit={onSubmit}>
        <label className="composerLabel" htmlFor="rental-message">
          {hasConversation ? "Refine your request" : "Describe your ideal rental"}
        </label>
        <textarea
          ref={textareaRef}
          id="rental-message"
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          rows={2}
          maxLength={4000}
          placeholder={hasConversation ? "Refine your search…" : "2 bed under $2,500 in Austin, TX with parking"}
          disabled={loading}
        />
        <div className="composerFooter">
          <span>{draft.length > 3600 ? `${draft.length}/4000` : "Shift + Enter for a new line"}</span>
          <button type="submit" disabled={loading || !draft.trim()} aria-label={hasConversation ? "Refine search" : "Ask rental agent"}>
            <ArrowUpIcon />
          </button>
        </div>
      </form>
      <p className="agentDisclaimer">Recommendations cite available listing data. Verify details before applying.</p>
    </div>
  );
}
