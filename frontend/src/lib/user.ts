import { getSignedInEmail } from '../auth';
import { appConfig } from '../config';

/** The signed-in user's email: the Google account in google mode, the dev user otherwise. */
export function currentEmail(): string {
  return appConfig.authMode === 'google' ? (getSignedInEmail() ?? '') : appConfig.devUser;
}
