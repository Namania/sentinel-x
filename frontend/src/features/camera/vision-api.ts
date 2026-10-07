export type DetectedPerson = {
  box: { x: number; y: number; width: number; height: number };
  confidence: number;
  identity: string | null;
  identity_confidence: number | null;
  is_intruder: boolean;
  blacklisted_as: string | null;
  blacklist_confidence: number | null;
  is_blacklisted: boolean;
};

export type DetectionSnapshot = {
  analyzed_at: string;
  has_intruder: boolean;
  has_blacklisted: boolean;
  people: DetectedPerson[];
};
