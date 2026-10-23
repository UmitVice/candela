package chat

import "strings"

const (
	openTag  = "<think>"
	closeTag = "</think>"
)

// splitter separates <think>…</think> spans from answer text in a token stream whose
// chunks may cut a tag in half.
type splitter struct {
	inThink bool
	pending string
	started bool
}

type piece struct {
	reasoning bool
	text      string
}

func (s *splitter) push(chunk string) []piece {
	s.pending += chunk
	var out []piece
	for s.pending != "" {
		tag := openTag
		if s.inThink {
			tag = closeTag
		}
		if i := strings.Index(s.pending, tag); i >= 0 {
			out = s.emit(out, s.pending[:i])
			s.pending = s.pending[i+len(tag):]
			s.inThink = !s.inThink
			continue
		}
		keep := partialSuffix(s.pending, tag)
		out = s.emit(out, s.pending[:len(s.pending)-keep])
		s.pending = s.pending[len(s.pending)-keep:]
		break
	}
	return out
}

func (s *splitter) flush() []piece {
	rest := s.pending
	s.pending = ""
	return s.emit(nil, rest)
}

func (s *splitter) emit(out []piece, text string) []piece {
	if text == "" {
		return out
	}
	if !s.inThink && !s.started {
		text = strings.TrimLeft(text, " \t\r\n")
		if text == "" {
			return out
		}
		s.started = true
	}
	return append(out, piece{reasoning: s.inThink, text: text})
}

func partialSuffix(s, tag string) int {
	for n := min(len(tag)-1, len(s)); n > 0; n-- {
		if strings.HasSuffix(s, tag[:n]) {
			return n
		}
	}
	return 0
}
