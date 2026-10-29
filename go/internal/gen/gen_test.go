package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

const specPath = "../../../openapi/vaquill-us.json"

func TestGeneratedFilesMatchTheSpec(t *testing.T) {
	spec, err := os.ReadFile(specPath)
	if err != nil {
		t.Fatal(err)
	}
	files, _, err := Generate(spec)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != 3 {
		t.Fatalf("generator emitted %d files, want 3", len(files))
	}
	for name, want := range files {
		got, err := os.ReadFile(filepath.Join("..", "..", name))
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, want) {
			t.Errorf("%s is stale: run `go generate ./...` in the go/ directory and commit the result", name)
		}
	}
}

func TestGenerateIsDeterministic(t *testing.T) {
	spec, err := os.ReadFile(specPath)
	if err != nil {
		t.Fatal(err)
	}
	a, _, err := Generate(spec)
	if err != nil {
		t.Fatal(err)
	}
	b, _, _ := Generate(spec)
	for name := range a {
		if !bytes.Equal(a[name], b[name]) {
			t.Errorf("%s differs between runs", name)
		}
	}
}

func TestGenerateRejectsBadSpec(t *testing.T) {
	if _, _, err := Generate([]byte("not json")); err == nil {
		t.Error("expected an error for malformed JSON")
	}
}

func TestNoEmDashesInGeneratedCode(t *testing.T) {
	spec, _ := os.ReadFile(specPath)
	files, _, err := Generate(spec)
	if err != nil {
		t.Fatal(err)
	}
	for name, data := range files {
		if bytes.Contains(data, []byte("\u2014")) || bytes.Contains(data, []byte("\u2013")) {
			t.Errorf("%s contains a dash that is not ASCII", name)
		}
	}
}
