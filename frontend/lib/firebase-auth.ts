import { getApp, getApps, initializeApp } from "firebase/app";
import { getAuth, signInAnonymously, type User } from "firebase/auth";

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

export async function getFirebaseIdToken(): Promise<string | undefined> {
  if (authMode() === "disabled") return undefined;

  const auth = getAuth(firebaseApp());
  if (auth.currentUser) return auth.currentUser.getIdToken();

  if (!anonymousSignIn) {
    anonymousSignIn = signInAnonymously(auth)
      .then((credential) => credential.user)
      .finally(() => {
        anonymousSignIn = undefined;
      });
  }

  const user = await anonymousSignIn;
  return user.getIdToken();
}
