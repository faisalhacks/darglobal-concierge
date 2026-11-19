// "Try it live": hand a question to the chat. On the home page the chat listens for ASK_EVENT; from any other page
// the question travels as /?ask=<question>, which the chat reads once on mount and then removes from the address bar.
export const ASK_EVENT = "concierge:ask";
export const ASK_PARAM = "ask";

export function askInChat(question: string) {
  window.dispatchEvent(new CustomEvent<string>(ASK_EVENT, { detail: question }));
}

export const askHref = (question: string) => `/?${ASK_PARAM}=${encodeURIComponent(question)}`;
