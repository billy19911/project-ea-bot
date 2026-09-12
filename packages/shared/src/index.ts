/**
 * Shared TypeScript types and utilities for EA Bot
 * 
 * @packageDocumentation
 * 
 * This package contains common types, interfaces, and utility functions
 * used across the monorepo applications.
 */

/**
 * Common API response wrapper
 */
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}

/**
 * Pagination parameters for list endpoints
 */
export interface PaginationParams {
  page?: number;
  limit?: number;
  offset?: number;
}

/**
 * Paginated response with metadata
 */
export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  limit: number;
  totalPages: number;
}

/**
 * EA Bot configuration interface
 */
export interface EobotConfig {
  apiKey: string;
  apiSecret: string;
  tradingPair: string;
  timeframe: string;
  dryRun?: boolean;
}

/**
 * Trade signal data structure
 */
export interface TradeSignal {
  id: string;
  timestamp: number;
  pair: string;
  side: 'buy' | 'sell';
  price: number;
  reason: string;
  confidence: number;
}

/**
 * Health check response format
 */
export interface HealthCheck {
  status: 'healthy' | 'unhealthy';
  timestamp: number;
  services: Record<string, 'up' | 'down'>;
}

/**
 * Format a Unix timestamp to ISO string
 */
export function formatTimestamp(timestamp: number): string {
  return new Date(timestamp).toISOString();
}

/**
 * Clamp a number between min and max values
 */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * Generate a unique ID string
 */
export function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

/**
 * Create a promise-based delay
 */
export function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
