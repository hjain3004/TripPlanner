import { describe, expect, it } from "vitest";
import {
  answerSourceLabel,
  isAnswerComplete,
  progressLabel,
  type InterviewQuestion,
} from "../src/components/product/conversational/conversational-types";

const requiredQuestion: InterviewQuestion = {
  id: "destination",
  title: "Where are you going?",
  step: 1,
  totalSteps: 10,
  required: true,
  control: { kind: "text" },
};

describe("conversational presentation helpers", () => {
  it("keeps progress labels bounded and human-readable", () => {
    expect(progressLabel(6, 10)).toBe("6 of 10");
    expect(progressLabel(0, 0)).toBe("1 of 1");
    expect(progressLabel(14, 10)).toBe("10 of 10");
  });

  it("requires meaningful answers for required questions", () => {
    expect(isAnswerComplete(requiredQuestion, null)).toBe(false);
    expect(isAnswerComplete(requiredQuestion, "   ")).toBe(false);
    expect(isAnswerComplete(requiredQuestion, "Singapore")).toBe(true);
    expect(isAnswerComplete({ ...requiredQuestion, required: false }, null)).toBe(true);
  });

  it("names profile, trip, and delegated answer sources consistently", () => {
    expect(answerSourceLabel("profile")).toBe("Profile default");
    expect(answerSourceLabel("trip")).toBe("This trip");
    expect(answerSourceLabel("delegated", true)).toBe("Chosen for me");
  });
});
