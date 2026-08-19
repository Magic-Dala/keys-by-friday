import { afterEach, beforeEach, expect, it, vi } from "vitest";

const firebase = vi.hoisted(() => {
  const auth = { currentUser: null as TestUser | null };
  const credentialFromError = vi.fn();
  const emailCredential = vi.fn();
  class TestGoogleAuthProvider {
    static credentialFromError = credentialFromError;
  }
  class TestEmailAuthProvider {
    static credential = emailCredential;
  }

  return {
    app: {},
    auth,
    getApp: vi.fn(),
    getApps: vi.fn(),
    getAuth: vi.fn(),
    initializeApp: vi.fn(),
    linkWithCredential: vi.fn(),
    linkWithPopup: vi.fn(),
    onAuthStateChanged: vi.fn(),
    createUserWithEmailAndPassword: vi.fn(),
    signInAnonymously: vi.fn(),
    signInWithCredential: vi.fn(),
    signInWithEmailAndPassword: vi.fn(),
    signInWithPopup: vi.fn(),
    signOut: vi.fn(),
    credentialFromError,
    emailCredential,
    TestGoogleAuthProvider,
    TestEmailAuthProvider,
  };
});

interface TestUser {
  uid: string;
  isAnonymous: boolean;
  displayName?: string | null;
  email?: string | null;
  getIdToken: ReturnType<typeof vi.fn>;
}

vi.mock("firebase/app", () => ({
  getApp: firebase.getApp,
  getApps: firebase.getApps,
  initializeApp: firebase.initializeApp,
}));

vi.mock("firebase/auth", () => ({
  createUserWithEmailAndPassword: firebase.createUserWithEmailAndPassword,
  EmailAuthProvider: firebase.TestEmailAuthProvider,
  getAuth: firebase.getAuth,
  GoogleAuthProvider: firebase.TestGoogleAuthProvider,
  linkWithCredential: firebase.linkWithCredential,
  linkWithPopup: firebase.linkWithPopup,
  onAuthStateChanged: firebase.onAuthStateChanged,
  signInAnonymously: firebase.signInAnonymously,
  signInWithCredential: firebase.signInWithCredential,
  signInWithEmailAndPassword: firebase.signInWithEmailAndPassword,
  signInWithPopup: firebase.signInWithPopup,
  signOut: firebase.signOut,
}));

import {
  getFirebaseIdToken,
  observeFirebaseUser,
  createAccountWithEmail,
  signInWithEmail,
  signInWithGoogle,
  signOutToAnonymous,
} from "@/lib/firebase-auth";

function user(uid: string, isAnonymous: boolean, token = `${uid}-token`): TestUser {
  return {
    uid,
    isAnonymous,
    displayName: isAnonymous ? null : "Ada Lovelace",
    email: isAnonymous ? null : "ada@example.com",
    getIdToken: vi.fn().mockResolvedValue(token),
  };
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_AUTH_MODE", "firebase");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_API_KEY", "api-key");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN", "example.firebaseapp.com");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_PROJECT_ID", "project-id");
  vi.stubEnv("NEXT_PUBLIC_FIREBASE_APP_ID", "app-id");

  firebase.auth.currentUser = null;
  firebase.getApps.mockReset().mockReturnValue([firebase.app]);
  firebase.getApp.mockReset().mockReturnValue(firebase.app);
  firebase.getAuth.mockReset().mockReturnValue(firebase.auth);
  firebase.initializeApp.mockReset().mockReturnValue(firebase.app);
  firebase.linkWithCredential.mockReset();
  firebase.linkWithPopup.mockReset();
  firebase.onAuthStateChanged.mockReset();
  firebase.createUserWithEmailAndPassword.mockReset();
  firebase.signInAnonymously.mockReset();
  firebase.signInWithCredential.mockReset();
  firebase.signInWithEmailAndPassword.mockReset();
  firebase.signInWithPopup.mockReset();
  firebase.signOut.mockReset();
  firebase.credentialFromError.mockReset();
  firebase.emailCredential.mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

it("preserves automatic anonymous access for API token requests", async () => {
  const anonymousUser = user("anon-1", true);
  firebase.signInAnonymously.mockResolvedValue({ user: anonymousUser });

  await expect(getFirebaseIdToken()).resolves.toBe("anon-1-token");

  expect(firebase.signInAnonymously).toHaveBeenCalledWith(firebase.auth);
});

it("observes Firebase auth state for the account controls", () => {
  const listener = vi.fn();
  const unsubscribe = vi.fn();
  firebase.onAuthStateChanged.mockReturnValue(unsubscribe);

  expect(observeFirebaseUser(listener)).toBe(unsubscribe);
  expect(firebase.onAuthStateChanged).toHaveBeenCalledWith(firebase.auth, listener);
});

it("links Google to an anonymous account so its UID is preserved", async () => {
  const anonymousUser = user("anon-1", true);
  const upgradedUser = user("anon-1", false);
  firebase.auth.currentUser = anonymousUser;
  firebase.linkWithPopup.mockResolvedValue({ user: upgradedUser });

  await expect(signInWithGoogle()).resolves.toBe(upgradedUser);

  expect(firebase.linkWithPopup).toHaveBeenCalledWith(
    anonymousUser,
    expect.any(firebase.TestGoogleAuthProvider),
  );
  expect(firebase.signInWithPopup).not.toHaveBeenCalled();
});

it("falls back to the existing Google account when the credential is already in use", async () => {
  const anonymousUser = user("anon-1", true);
  const googleUser = user("google-2", false);
  const recoveredCredential = { providerId: "google.com" };
  const collision = { code: "auth/credential-already-in-use" };
  firebase.auth.currentUser = anonymousUser;
  firebase.linkWithPopup.mockRejectedValue(collision);
  firebase.credentialFromError.mockReturnValue(recoveredCredential);
  firebase.signInWithCredential.mockResolvedValue({ user: googleUser });

  await expect(signInWithGoogle()).resolves.toBe(googleUser);

  expect(firebase.credentialFromError).toHaveBeenCalledWith(collision);
  expect(firebase.signInWithCredential).toHaveBeenCalledWith(
    firebase.auth,
    recoveredCredential,
  );
});

it("signs in with a Google popup when there is no anonymous account to upgrade", async () => {
  const googleUser = user("google-2", false);
  firebase.signInWithPopup.mockResolvedValue({ user: googleUser });

  await expect(signInWithGoogle()).resolves.toBe(googleUser);

  expect(firebase.signInWithPopup).toHaveBeenCalledWith(
    firebase.auth,
    expect.any(firebase.TestGoogleAuthProvider),
  );
});

it("links email/password to an anonymous account so its UID is preserved", async () => {
  const anonymousUser = user("anon-1", true);
  const upgradedUser = user("anon-1", false);
  const emailCredential = { providerId: "password" };
  firebase.auth.currentUser = anonymousUser;
  firebase.emailCredential.mockReturnValue(emailCredential);
  firebase.linkWithCredential.mockResolvedValue({ user: upgradedUser });

  await expect(createAccountWithEmail("ada@example.com", "secret123")).resolves.toBe(upgradedUser);

  expect(firebase.emailCredential).toHaveBeenCalledWith("ada@example.com", "secret123");
  expect(firebase.linkWithCredential).toHaveBeenCalledWith(anonymousUser, emailCredential);
  expect(firebase.createUserWithEmailAndPassword).not.toHaveBeenCalled();
});

it("falls back to the existing email/password account when the email is already in use", async () => {
  const anonymousUser = user("anon-1", true);
  const existingUser = user("email-2", false);
  const emailCredential = { providerId: "password" };
  firebase.auth.currentUser = anonymousUser;
  firebase.emailCredential.mockReturnValue(emailCredential);
  firebase.linkWithCredential.mockRejectedValue({ code: "auth/email-already-in-use" });
  firebase.signInWithEmailAndPassword.mockResolvedValue({ user: existingUser });

  await expect(createAccountWithEmail("ada@example.com", "secret123")).resolves.toBe(existingUser);

  expect(firebase.signInWithEmailAndPassword).toHaveBeenCalledWith(
    firebase.auth,
    "ada@example.com",
    "secret123",
  );
});

it("creates a new email/password account when there is no anonymous user to upgrade", async () => {
  const emailUser = user("email-3", false);
  firebase.createUserWithEmailAndPassword.mockResolvedValue({ user: emailUser });

  await expect(createAccountWithEmail("ada@example.com", "secret123")).resolves.toBe(emailUser);

  expect(firebase.createUserWithEmailAndPassword).toHaveBeenCalledWith(
    firebase.auth,
    "ada@example.com",
    "secret123",
  );
});

it("signs in to an existing email/password account", async () => {
  const emailUser = user("email-2", false);
  firebase.signInWithEmailAndPassword.mockResolvedValue({ user: emailUser });

  await expect(signInWithEmail("ada@example.com", "secret123")).resolves.toBe(emailUser);

  expect(firebase.signInWithEmailAndPassword).toHaveBeenCalledWith(
    firebase.auth,
    "ada@example.com",
    "secret123",
  );
});

it("establishes a fresh anonymous session immediately after Google sign-out", async () => {
  const googleUser = user("google-2", false);
  const freshAnonymousUser = user("anon-3", true);
  firebase.auth.currentUser = googleUser;
  firebase.signOut.mockResolvedValue(undefined);
  firebase.signInAnonymously.mockResolvedValue({ user: freshAnonymousUser });

  await expect(signOutToAnonymous()).resolves.toBe(freshAnonymousUser);

  expect(firebase.signOut).toHaveBeenCalledWith(firebase.auth);
  expect(firebase.signInAnonymously).toHaveBeenCalledWith(firebase.auth);
});
