import { z } from "zod";

// Re-export dari envSchema agar consumer packages bisa validasi sendiri
export { envSchema, type Environment } from "./envSchema";
