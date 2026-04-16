/**
 * Auth shim for desktop — replaces react-oidc-context.
 *
 * Provides useAuth() that always returns authenticated state.
 * No actual authentication — local app doesn't need it.
 */

const mockUser = {
  id_token: "local",
  access_token: "local",
  profile: { sub: "local-user", email: "local@sdpm.app" },
};

export function useAuth() {
  return {
    isAuthenticated: true,
    user: mockUser,
    isLoading: false,
    error: null,
    signinRedirect: () => {},
    signoutRedirect: () => {},
    removeUser: () => Promise.resolve(),
  };
}

// re-export useAutoSignin as no-op (used by AutoSignin.tsx)
export function useAutoSignin() {
  return { isLoading: false, isAuthenticated: true, error: null };
}

// re-export AuthProvider as passthrough
export function AuthProvider({ children }: { children: React.ReactNode }) {
  return children;
}
