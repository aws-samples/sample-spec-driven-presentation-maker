/**
 * useAuth shim for desktop — replaces @/hooks/useAuth.
 *
 * Same interface as web-ui/src/hooks/useAuth.ts but always authenticated.
 */

export function useAuth() {
  return {
    isAuthenticated: true,
    user: {
      id_token: "local",
      access_token: "local",
      profile: { sub: "local-user", email: "local@sdpm.app" },
    },
    signIn: () => {},
    signOut: () => {},
    isLoading: false,
    error: null,
    token: "local",
  };
}
