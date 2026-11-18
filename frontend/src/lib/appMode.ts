/** Build-time switch: `VITE_APP_MODE=mock` produces a site that is only the
 * mock draft simulator (sign in, lobby, draft rooms, invite links) -- none
 * of the league tools. Must match the backend's APP_MODE, which stops
 * serving the other API routes too. */
export const MOCK_ONLY = import.meta.env.VITE_APP_MODE === "mock";
