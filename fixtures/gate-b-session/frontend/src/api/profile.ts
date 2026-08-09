import { sendJson } from "./client";

export interface UpdateProfileRequest {
  display_name: string;
  marketing_opt_in: boolean;
}

export interface Profile {
  display_name: string;
  marketing_opt_in: boolean;
}

export function updateProfile(
  request: UpdateProfileRequest,
): Promise<Profile> {
  return sendJson<Profile>("PUT", "/profile", request);
}
