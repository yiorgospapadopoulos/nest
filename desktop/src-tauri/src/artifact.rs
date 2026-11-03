//! Artifact pages, served from their own `nest-artifact:` address. A srcdoc frame would
//! inherit the app's policy, under which an artifact's scripts cannot run; a page served
//! here carries the artifact policy instead, and the app's policy stays strict.
//!
//! Each staged page is served once and then forgotten. The app counts this scheme as its
//! own, so a page that became the top-level document would get the app's commands; a page
//! that can be fetched only by the frame made for it never can.

use std::collections::hash_map::RandomState;
use std::collections::VecDeque;
use std::hash::{BuildHasher, Hasher};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use tauri::http::{header, Response, StatusCode};

use crate::platform;

pub const SCHEME: &str = "nest-artifact";
/// The same policy as ARTIFACT_CSP in web/src/screens/artifacts/html.ts (a test compares).
pub const CSP: &str = "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net/npm/ https://unpkg.com https://cdn.tailwindcss.com https://code.jquery.com; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; worker-src 'none'";
/// Pages staged but not yet loaded; past these the oldest go.
const MAX_PAGES: usize = 16;
const MAX_BYTES: usize = 64 * 1024 * 1024;

#[derive(Default)]
pub struct Artifacts {
    pages: Mutex<VecDeque<(String, String)>>,
}

impl Artifacts {
    /// Keeps the page until its frame loads it; returns the frame's address.
    pub fn stage(&self, html: String) -> String {
        let id = random_id();
        let mut pages = self.pages.lock().unwrap();
        pages.push_back((id.clone(), html));
        while pages.len() > 1
            && (pages.len() > MAX_PAGES
                || pages.iter().map(|(_, html)| html.len()).sum::<usize>() > MAX_BYTES)
        {
            pages.pop_front();
        }
        platform::custom_scheme_url(SCHEME, &id)
    }

    /// Forgets a page that was staged but never loaded (its reader closed first).
    pub fn release(&self, url: &str) {
        let id = id_of(url);
        self.pages
            .lock()
            .unwrap()
            .retain(|(staged, _)| staged != id);
    }

    /// The response for a request to `path` (`/<id>`): the page once, then 404.
    pub fn serve(&self, path: &str) -> Response<Vec<u8>> {
        let id = id_of(path);
        let page = {
            let mut pages = self.pages.lock().unwrap();
            let found = pages.iter().position(|(staged, _)| staged == id);
            found.and_then(|index| pages.remove(index))
        };
        let response = Response::builder()
            .header(header::CACHE_CONTROL, "no-store")
            .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
            .header(header::REFERRER_POLICY, "no-referrer");
        match page {
            Some((_, html)) => response
                .header(header::CONTENT_TYPE, "text/html; charset=utf-8")
                .header(header::CONTENT_SECURITY_POLICY, CSP)
                .body(html.into_bytes()),
            None => response
                .status(StatusCode::NOT_FOUND)
                .header(header::CONTENT_TYPE, "text/plain; charset=utf-8")
                .body(b"No such artifact page".to_vec()),
        }
        .expect("static headers are valid")
    }
}

fn id_of(url: &str) -> &str {
    let path = url.split(['?', '#']).next().unwrap_or_default();
    path.rsplit('/').next().unwrap_or_default()
}

/// 128 bits from the standard library's randomly keyed hasher.
fn random_id() -> String {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let count = NEXT.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|time| time.as_nanos())
        .unwrap_or_default();
    let part = |salt: u64| {
        let mut hasher = RandomState::new().build_hasher();
        hasher.write_u64(count);
        hasher.write_u64(salt);
        hasher.write_u128(nanos);
        hasher.finish()
    };
    format!("{:016x}{:016x}", part(1), part(2))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn path_of(url: &str) -> String {
        format!("/{}", id_of(url))
    }

    #[test]
    fn a_staged_page_is_served_once_with_the_artifact_policy() {
        let artifacts = Artifacts::default();
        let url = artifacts.stage("<p>hi</p>".to_owned());
        assert!(url.starts_with("nest-artifact://"), "{url}");

        let first = artifacts.serve(&path_of(&url));
        assert_eq!(first.status(), StatusCode::OK);
        assert_eq!(first.body(), b"<p>hi</p>");
        assert_eq!(first.headers()[header::CONTENT_SECURITY_POLICY], CSP);

        assert_eq!(
            artifacts.serve(&path_of(&url)).status(),
            StatusCode::NOT_FOUND
        );
    }

    #[test]
    fn unknown_and_released_pages_are_not_found() {
        let artifacts = Artifacts::default();
        assert_eq!(artifacts.serve("/nope").status(), StatusCode::NOT_FOUND);

        let url = artifacts.stage("<p>closed</p>".to_owned());
        artifacts.release(&url);
        assert_eq!(
            artifacts.serve(&path_of(&url)).status(),
            StatusCode::NOT_FOUND
        );
    }

    #[test]
    fn pages_never_loaded_do_not_pile_up() {
        let artifacts = Artifacts::default();
        let urls: Vec<String> = (0..MAX_PAGES + 4)
            .map(|n| artifacts.stage(format!("<p>{n}</p>")))
            .collect();

        assert_eq!(
            artifacts.serve(&path_of(&urls[0])).status(),
            StatusCode::NOT_FOUND
        );
        let last = urls.last().unwrap();
        assert_eq!(artifacts.serve(&path_of(last)).status(), StatusCode::OK);
        assert_ne!(id_of(&urls[1]), id_of(&urls[2]));
    }

    #[test]
    fn the_policy_matches_the_web_one() {
        let source = include_str!("../../../web/src/screens/artifacts/html.ts");
        assert!(
            source.contains(&format!("\"{CSP}\"")),
            "ARTIFACT_CSP in html.ts changed; copy it to artifact::CSP"
        );
    }
}
