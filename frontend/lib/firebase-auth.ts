import { getApp, getApps, initializeApp, type FirebaseError } from "firebase/app";
import {
  createUserWithEmailAndPassword,
  EmailAuthProvider,
  getAuth,
  GoogleAuthProvider,
  linkWithCredential,
  linkWithPopup,
  onAuthStateChanged,
  signInAnonymously,
  signInWithCredential,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type Unsubscribe,
  type User,
} from "firebase/auth";

type AuthMode = "disabled" | "firebase";

let anonymousSignIn: Promise<User> | undefined;

function authMode(): AuthMode {
  const mode = (process.env.NEXT_PUBLIC_AUTH_MODE ?? "disabled").trim().toLowerCase();
  if (mode !== "disabled" && mode !== "firebase") {
    throw new Error("NEXT_PUBLIC_AUTH_MODE must be 'disabled' or 'firebase'.");
  }
  return mode;
}

function requiredPublicSetting(name: string, value: string | undefined): string {
  const normalized = value?.trim();
  if (!normalized) throw new Error(`${name} is required when Firebase auth is enabled.`);
  return normalized;
}

function firebaseApp() {
  if (getApps().length > 0) return getApp();

  return initializeApp({
    apiKey: requiredPublicSetting(
      "NEXT_PUBLIC_FIREBASE_API_KEY",
      process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    ),
    authDomain: requiredPublicSetting(
      "NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN",
      process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    ),
    projectId: requiredPublicSetting(
      "NEXT_PUBLIC_FIREBASE_PROJECT_ID",
      process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    ),
    appId: requiredPublicSetting(
      "NEXT_PUBLIC_FIREBASE_APP_ID",
      process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
    ),
  });
}

function firebaseAuth() {
  return getAuth(firebaseApp());
}

async function ensureAnonymousUser(): Promise<User> {
  const auth = firebaseAuth();
  if (auth.currentUser) return auth.currentUser;

  if (!anonymousSignIn) {
    anonymousSignIn = signInAnonymously(auth)
      .then((credential) => credential.user)
      .finally(() => {
        anonymousSignIn = undefined;
      });
  }

  return anonymousSignIn;
}

function isCredentialCollision(error: unknown): error is FirebaseError {
  if (typeof error !== "object" || error === null || !("code" in error)) return false;
  const code = (error as { code?: unknown }).code;
  return code === "auth/credential-already-in-use";
}

function isEmailAccountCollision(error: unknown): error is FirebaseError {
  if (typeof error !== "object" || error === null || !("code" in error)) return false;
  const code = (error as { code?: unknown }).code;
  return (
    code === "auth/email-already-in-use" ||
    code === "auth/credential-already-in-use"
  );
}

export function observeFirebaseUser(listener: (user: User | null) => void): Unsubscribe {
  if (authMode() === "disabled") {
    listener(null);
    return () => undefined;
  }
  const auth = firebaseAuth();
  const unsubscribe = onAuthStateChanged(auth, listener);
  void ensureAnonymousUser().catch(() => undefined);
  return unsubscribe;
}

export async function signInWithGoogle(): Promise<User> {
  if (authMode() === "disabled") {
    throw new Error("Firebase auth is disabled.");
  }

  const auth = firebaseAuth();
  const provider = new GoogleAuthProvider();
  const currentUser = auth.currentUser;

  if (!currentUser?.isAnonymous) {
    return (await signInWithPopup(auth, provider)).user;
  }

  try {
    return (await linkWithPopup(currentUser, provider)).user;
  } catch (caught) {
    if (!isCredentialCollision(caught)) throw caught;
    const credential = GoogleAuthProvider.credentialFromError(caught);
    if (!credential) throw caught;
    return (await signInWithCredential(auth, credential)).user;
  }
}

export async function createAccountWithEmail(email: string, password: string): Promise<User> {
  if (authMode() === "disabled") {
    throw new Error("Firebase auth is disabled.");
  }

  const auth = firebaseAuth();
  const currentUser = auth.currentUser;

  if (!currentUser?.isAnonymous) {
    return (await createUserWithEmailAndPassword(auth, email, password)).user;
  }

  const credential = EmailAuthProvider.credential(email, password);
  try {
    return (await linkWithCredential(currentUser, credential)).user;
  } catch (caught) {
    if (!isEmailAccountCollision(caught)) throw caught;
    return (await signInWithEmailAndPassword(auth, email, password)).user;
  }
}

export async function signInWithEmail(email: string, password: string): Promise<User> {
  if (authMode() === "disabled") {
    throw new Error("Firebase auth is disabled.");
  }

  return (await signInWithEmailAndPassword(firebaseAuth(), email, password)).user;
}

export async function signOutToAnonymous(): Promise<User> {
  if (authMode() === "disabled") {
    throw new Error("Firebase auth is disabled.");
  }

  const auth = firebaseAuth();
  anonymousSignIn = undefined;
  await signOut(auth);
  const credential = await signInAnonymously(auth);
  return credential.user;
}

export async function getFirebaseIdToken(): Promise<string | undefined> {
  if (authMode() === "disabled") return undefined;

  const user = await ensureAnonymousUser();
  return user.getIdToken();
}
