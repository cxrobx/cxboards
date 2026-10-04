# CXBoards templates

Ready-made boards, filed by what you're using them for. One YAML file per template:
`templates/<use case>/<slug>.yaml`. The use cases and their order are in `categories.yaml`.

Most are modelled on the use cases in Milanote's public template gallery (each file's `source`
says which), rewritten in our own words; **Music** is ours. Nothing is in the library twice: the
loader refuses a slug, a name or a source used by two files.

## Using one

- **In the app:** New board, or right-click the sidebar ▸ *New board from template…*. Pick a use case
  on the left or search ("podcast outline", "brand workshop"). Double-click a template to make it
  straight away.
- **Agents and Ask:** `list_templates()` shows the use cases, `list_templates(category="podcasting")`
  or `list_templates(query="episode outline")` finds one, and
  `create_board("", template="podcast-outline")` makes it (the title defaults to the template's name).
- **HTTP:** `GET /api/templates?q=&category=`, then `POST /api/boards {"template": "<slug>"}`.

A board made from a template is one undo step. Edit a file and the next board made from it uses the
edit; there's no restart.

## Writing one

```yaml
name: Podcast episode plan            # unique in the library
use_when: Planning one episode, from the idea to the promotion after it.
also: [content-creation]              # other use cases it belongs in (optional)
source: https://…                     # what it was modelled on (optional, unique)
theme: studio                         # a board theme preset (optional)
cards:                                # in reading order, left to right
  - note: |
      # *Episode title*
      **What the listener leaves with:**
    color: amber                      # amber clay green cyan violet magenta
    width: 340                        # 200–600
  - break                             # start a new row
  - column: Research
    cards:                            # notes, to-dos and swatches
      - note: Three sources worth quoting.
      - todo: Before recording
        items: [Book the guest, Send the questions]
  - swatch: "#E0A33A"
    text: Cover accent
  - board: Guest notes                # a board inside the board (two deep at most)
    folder: false
    cards:
      - note: One board per guest.
```

No coordinates: the cards are laid out in rows, and the build never overlaps two cards. To-do
items are plain text (no markdown). Check a file with
`.venv/bin/python scripts/check-template.py templates/<use case>/<slug>.yaml`, then refresh the index
below with `.venv/bin/python scripts/template-index.py`. `pytest` builds every template and fails if
this index is stale.

## Index

<!-- index:start -->

**213 templates in 38 use cases.** Each lives in exactly one folder; a template that serves another use case too is listed there in *italics*.

### Music

Studio sessions, projects and releases — planning the work and getting it out.

| Template | Use it when | Slug |
|---|---|---|
| [Artist pipeline](music/artist-pipeline.yaml) | Working with artists as a producer — who you've found, where each conversation is, the next step for every one, and who to come back to later. | `artist-pipeline` |
| [Catalog map](music/catalog-map.yaml) | Seeing the whole body of work at once — what's out and what it means, what's loading, what's resting, what's in the vault, and where it all sits in The Arc. | `catalog-map` |
| [Client song](music/client-song.yaml) | Producing a song for an artist — the discovery call, the session and debrief, the paperwork in the right order, and a delivery package that doesn't bounce back. | `client-song` |
| [EP or album](music/album-process.yaml) | Running a project from the first seeds to the release — a thesis held loosely, the shelf you pick from, every song's board, the sequence, and the listen that says it's done. | `album-process` |
| [Live set plan](music/live-set-plan.yaml) | Preparing a show or a DJ / live set — the setlist and its energy, the transitions, the gear and stems, and the run of the day. | `live-set-plan` |
| [Mix revision notes](music/mix-revision-notes.yaml) | Going back and forth on a mix or master — notes on each MM pass, by section and time stamp, until the full listen says it's done. | `mix-revision-notes` |
| [Reference track breakdown](music/reference-track-breakdown.yaml) | Studying a song you want to learn from — its arrangement section by section, the sounds, the mix choices — so you can take one thing into your own work. | `reference-track-breakdown` |
| [Release (EP or album)](music/release-project.yaml) | Putting out a project — the tracklist of chosen masters, the cover and essay, content shot during the mix week, and the date set once it's all ready. | `release-project` |
| [Release (single)](music/release-single.yaml) | Putting out one song — the date opens once the master and cover are done, with about two weeks of runway, then the look back a month later. | `release-single` |
| [Session plan](music/session-plan.yaml) | Opening a studio session in FL — the goal in one sentence, the references, a stretch of playing before choosing, and a few honest words after. | `session-plan` |
| [Sketchbook](music/sketchbook.yaml) | Keeping a month of sketches and ideas in one place — what you made, what keeps coming back, and which ideas went into which song. | `sketchbook` |
| [Song](music/song.yaml) | Carrying one song from the first sketch to the master — the feeling it's after, its versions, the lyrics, the credits, and how you'll know it's done. | `song` |
| [Songs in progress](music/songs-in-progress.yaml) | Seeing every song you're carrying at once — where each one is, which are resting, and which are done — without counting anything. | `songs-in-progress` |
| [Songwriting session](music/songwriting-session.yaml) | Writing toward a song — get everything out first, choose afterwards, then shape the keepers into verse, hook and bridge. | `songwriting-session` |

### Moodboards

Collect images, colour and references to set a visual direction.

| Template | Use it when | Slug |
|---|---|---|
| [Brand board](moodboards/brand-board.yaml) | Pinning down how a brand looks and sounds — logo, palette, type, imagery and voice — on one page everyone works from. | `brand-board` |
| [Fashion moodboard](moodboards/fashion-moodboard.yaml) | Setting the look for a collection, a shoot or a styling job — references, silhouettes, fabrics and palette — before anything gets made. | `fashion-moodboard` |
| [Illustration moodboard](moodboards/illustration-moodboard.yaml) | Finding the style for an illustration job — line, colour, texture, characters and composition — before you start drawing for real. | `illustration-moodboard` |
| [Inspiration board](moodboards/inspiration-board.yaml) | Starting any creative project by collecting what excites you — images, clips, words — and sorting it until a direction shows up. | `inspiration-board` |
| [Packaging design moodboard](moodboards/packaging-design-moodboard.yaml) | Setting the look of a product's packaging — shelf context, references, materials, colour and type — before you design the pack. | `packaging-design-moodboard` |
| [Vision board](moodboards/vision-board.yaml) | Picturing the year or the life you're working toward — goals in detail, images that stand for them, and words to come back to every day. | `vision-board` |
| [Web design moodboard](moodboards/web-design-moodboard.yaml) | Setting the visual direction for a website — look, layout, interface pieces and motion — so everyone agrees on it before design starts. | `web-design-moodboard` |
| [Wedding moodboard](moodboards/wedding-moodboard.yaml) | Setting the style for a wedding — yours or a client's — from the venue and the outfits to the flowers, the paper and the colours. | `wedding-moodboard` |
| *[Architecture moodboard](architecture/architecture-moodboard.yaml)* | Setting the look and atmosphere of a building project — form, materials, textures, light and colour — from collected images before the design is drawn. | `architecture-moodboard` |
| *[Character design moodboard](creative-writing/character-design-moodboard.yaml)* | Finding what a character looks like and lives among — face, clothes, the things they love, the places they go — before you describe them on the page. | `character-design-moodboard` |
| *[Event moodboard](events/event-moodboard.yaml)* | Defining the look and atmosphere of an event — theme, colour, venue, props and the small details — so clients and suppliers can react before anything is booked. | `event-moodboard` |
| *[Film moodboard](filmmaking/filmmaking-moodboard.yaml)* | Setting the look and feel of a film for cast and crew — light, colour, sets, wardrobe and framing — in images before anyone builds or shoots. | `filmmaking-moodboard` |
| *[Game design moodboard](game-design/game-design-moodboard.yaml)* | Setting the look and feel of a game — characters, places, textures, colour, motion and sound — so the team shares one picture of it before production. | `game-design-moodboard` |
| *[Graphic design moodboard](graphic-design/graphic-design-moodboard.yaml)* | Setting the visual direction for a design project — imagery, colour, type, texture and layout — from existing references before you design anything new. | `graphic-design-moodboard` |
| *[Interior design moodboard](interior-design/interior-design-moodboard.yaml)* | Setting the look of a room or venue — images, colours, materials and furniture together — so the client agrees on a direction before anything is bought. | `interior-design-moodboard` |
| *[Logo moodboard](logo-design/logo-moodboard.yaml)* | Exploring the visual direction for a logo — references, imagery, colour, type and pattern — and getting it agreed before you draw. | `logo-moodboard` |
| *[Marketing campaign moodboard](marketing-campaign/marketing-campaign-moodboard.yaml)* | Setting the look of a campaign before design starts — the colours, type, imagery and branding cues it should share, pinned up where everyone can see them. | `marketing-campaign-moodboard` |
| *[Motion design moodboard](motion-design/motion-design-moodboard.yaml)* | Setting the visual and animation direction for a motion piece — characters, type, colour, and real examples of how things should move and sound. | `motion-design-moodboard` |
| *[Novel moodboard](creative-writing/novel-moodboard.yaml)* | Collecting the images, colours, clips and textures that hold the feeling of your story, so you can return to it every time you sit down to write. | `novel-moodboard` |
| *[Photography moodboard](photography/photography-moodboard.yaml)* | Setting the look of a shoot before it happens — the light, the framing, the colour — so photographer, crew and client picture the same images. | `photography-moodboard` |

### Brainstorming

Get ideas out, cluster them and pick the ones worth pursuing.

| Template | Use it when | Slug |
|---|---|---|
| [5 whys](brainstorming/5-whys.yaml) | Getting past the symptom of a problem to its root cause by asking why five times, then deciding what to change so it doesn't come back. | `5-whys` |
| [Brainstorming workshop](brainstorming/brainstorming-workshop.yaml) | Running a brainstorm with a group — framing the question, getting ideas out fast, clustering them and leaving with a few to pursue. | `brainstorming-workshop` |
| [Concept map](brainstorming/concept-map.yaml) | Making sense of a complex topic by laying out its ideas and naming how each one relates to the others. | `concept-map` |
| [Design exploration](brainstorming/design-exploration.yaml) | Trying out a few visual directions for a new project side by side, using existing images, colour and type, before opening a design tool. | `design-exploration` |
| [Flow chart](brainstorming/flow-chart.yaml) | Mapping a workflow or decision process step by step, so you can see where it branches, stalls or could be simpler. | `flow-chart` |
| [Inspiration library](brainstorming/inspiration-library.yaml) | Keeping a running collection of references — images, writing, colour, type, ideas — sorted so you can find them when a project needs them. | `inspiration-library` |
| [Mind map](brainstorming/mind-map.yaml) | Exploring a topic outward from one central idea — branches, then sub-branches — to see everything it touches before you organise it. | `mind-map` |

### Creative briefs

Agree on the problem, the audience and what good looks like before the work starts.

| Template | Use it when | Slug |
|---|---|---|
| [Advertising brief](creative-briefs/advertising-brief.yaml) | Briefing a creative team on an ad campaign — the business problem, the audience, and the one idea the work has to land. | `advertising-brief` |
| [Animation brief](creative-briefs/animation-brief.yaml) | Commissioning or planning an animated piece — the story, the look, who it's for, what gets delivered and when. | `animation-brief` |
| [App design brief](creative-briefs/app-design-brief.yaml) | Briefing the design of a mobile app — who it's for, what it does in its first version, the platforms and the constraints — before any screens are drawn. | `app-design-brief` |
| [Brand strategy brief](creative-briefs/brand-strategy-brief.yaml) | Setting up a brand strategy project — the story so far, the value it offers, who buys and why — so the team works toward one picture. | `brand-strategy-brief` |
| [Digital campaign brief](creative-briefs/digital-campaign-brief.yaml) | Planning an online marketing campaign — the goal, the audience, the channels and message, and the numbers you'll judge it by. | `digital-campaign-brief` |
| [Illustration design brief](creative-briefs/illustration-brief.yaml) | Commissioning an illustration — what it shows, where it'll be used, the style you're after, and the deadlines. | `illustration-brief` |
| [Market research brief](creative-briefs/market-research-brief.yaml) | Briefing a research study so the researcher can pick the right method — the decision it informs, who to study, and what's already known. | `market-research-brief` |
| [Media planning brief](creative-briefs/media-planning-brief.yaml) | Briefing a media plan — who you need to reach, where and when, with what budget — before any placements are bought. | `media-planning-brief` |
| [Press release brief](creative-briefs/press-release-brief.yaml) | Briefing whoever writes a press release — the news, the messages, the words to use and avoid, and who it's going to. | `press-release-brief` |
| [SEO brief](creative-briefs/seo-brief.yaml) | Planning search work for a site — the goals, the searches worth winning, the pages to fix and the links worth earning. | `seo-brief` |
| [Social media campaign brief](creative-briefs/social-media-campaign-brief.yaml) | Planning a social campaign — the goal, the voice, the channels and the content — so everyone posting it pulls the same way. | `social-media-campaign-brief` |
| [UI design brief](creative-briefs/ui-design-brief.yaml) | Briefing an interface design project so collaborators can quote and start — the aims, the process, the existing styles and what they'll hand over. | `ui-design-brief` |
| [UX research brief](creative-briefs/ux-research-brief.yaml) | Setting up a user research project — what you need to learn, from whom, by which method, and what's already known. | `ux-research-brief` |
| [Video creative brief](creative-briefs/video-creative-brief.yaml) | Briefing a video shoot or edit — the goal, the message, the shots that matter and how the result will be judged. | `video-creative-brief` |
| [Website design brief](creative-briefs/website-design-brief.yaml) | Briefing a website build before anyone writes code — why it's happening, what success looks like, who it's for and how the brand should come through. | `website-design-brief` |
| *[Design brief](graphic-design/design-brief.yaml)* | Agreeing on a design job with a client before the work starts — the project, the goals, the audience, budget and timeline, examples, and what to avoid. | `design-brief` |
| *[Event brief](events/event-brief.yaml)* | Briefing a production team on an event — what it's for, where it happens, what guests should experience and how it should look — before the run sheet gets written. | `event-brief` |
| *[Interior design brief](interior-design/interior-design-brief.yaml)* | Starting an interior project with a client — why it's happening, the rooms and requirements, who uses the space and the look they have in mind. | `interior-design-brief` |
| *[Logo design brief](logo-design/logo-design-creative-brief.yaml)* | Writing the brief for a new logo — purpose, personality, audience, where it'll be used and what the client likes — so the designer starts with everything. | `logo-design-creative-brief` |
| *[Marketing brief](marketing-campaign/marketing-brief.yaml)* | Starting a marketing campaign with the client or team — the background, goals, brand, audience and the numbers it'll be judged on — written down before the work starts. | `marketing-brief` |
| *[Model brief](photography/model-brief.yaml)* | Briefing a model agency on a campaign so they can put forward the right people and everyone arrives knowing the look, the shots and the terms. | `model-brief` |
| *[Motion design brief](motion-design/motion-design-brief.yaml)* | Agreeing with a client what an animation is for, what it must say, who it's for and exactly what gets delivered, before a frame is designed. | `motion-design-brief` |
| *[Photoshoot brief](photography/photoshoot-brief.yaml)* | Briefing a photographer and their team on a shoot — the client, the subject, the goals and every deliverable — so the images land on the first try. | `photoshoot-brief` |

### Project plans

Scope, schedule and track a piece of work from kickoff to done.

| Template | Use it when | Slug |
|---|---|---|
| [Academic project plan](project-plans/academic-plan.yaml) | Planning an academic project or a course — the objectives, the method, the schedule around classes and the work broken into steps. | `academic-plan` |
| [Illustration project plan](project-plans/illustration-plan.yaml) | Planning an illustration job from brief to final files — the objectives, the style and medium, the references, the dates and the deliverables. | `illustration-plan` |
| [UX project plan](project-plans/ux-project-plan.yaml) | Running a UX design project — the objectives, the people you're designing for, research and testing, milestones and tasks — in one place. | `ux-project-plan` |
| *[Architecture project plan](architecture/architecture-project-plan.yaml)* | Running an architecture project from one hub — the brief, the work at each design stage, the drawings, the moodboard and the team. | `architecture-project-plan` |
| *[Campaign plan](marketing-campaign/campaign-plan.yaml)* | Turning an approved brief into a campaign you can run — the background, the goals and deliverables, the budget, the timeline and the creative direction. | `campaign-plan` |
| *[Event planning](events/event-plan.yaml)* | Planning an event from the first idea to the day after — objectives, dates, venue, suppliers, budget and the task list — in one place. | `event-plan` |
| *[Film pre-production](filmmaking/pre-production-plan.yaml)* | Running a film's whole pre-production from one hub — the ideas, the look, the storyboard, the shot list and the call sheet, with the workflow and gear checklists beside them. | `pre-production-plan` |
| *[Game design document](game-design/game-design-document.yaml)* | Running a whole game project from one hub — the vision, the brainstorm, the look, the world, the levels, the characters and the launch — instead of a long document nobody reads. | `game-design-document` |
| *[Graphic design project plan](graphic-design/graphic-design-project-plan.yaml)* | Running a design project from brief to final files — the brief, research, concepts, development and delivery — with the dates and tasks in one place. | `graphic-design-project-plan` |
| *[Interior design project plan](interior-design/interior-design-plan.yaml)* | Running a whole interior project in one place — the brief, the moodboard and the shopping list as boards, plus the checklists that get it from idea to installed. | `interior-design-plan` |
| *[Motion design project plan](motion-design/motion-design-plan.yaml)* | Running a motion design job from one hub — brief, ideas, moodboard, storyboard and style frames — with the workflow checklist beside them. | `motion-design-plan` |
| *[Novel plan](creative-writing/novel-plan.yaml)* | Running a whole novel from one board — the idea, research, inspiration, characters and outline each in their own board, with the checklists that take it from first draft to print. | `novel-plan` |
| *[Photoshoot plan](photography/photoshoot-plan.yaml)* | Running a whole shoot from one place — the brief, the moodboard, the shot list, the call sheet and the selects each get a board, with the workflow and gear checklists beside them. | `photoshoot-plan` |
| *[Website plan](website-design/website-plan.yaml)* | Running a website project from one hub — brief, audience, visual direction, sitemap and content — with the checklists that move it from plan to launch. | `website-plan` |

### Productivity

Plan your days, weeks and goals, and keep the list honest.

| Template | Use it when | Slug |
|---|---|---|
| [Eisenhower matrix](productivity/eisenhower-matrix.yaml) | Sorting a pile of tasks by how urgent and how important each one is, so you know what to do now, schedule, hand off or drop. | `eisenhower-matrix` |
| [Team planner](productivity/team-planner.yaml) | Managing a team's workload in one view — the priorities, who's on what with due dates, meeting notes and anything blocking the work. | `team-planner` |
| [Weekly plan](productivity/weekly-plan.yaml) | Planning your week on Sunday or Monday — the few goals that matter, what lands on each day, and a look back on Friday at what actually happened. | `weekly-plan` |
| *[Kanban board](product-management/kanban-board.yaml)* | Running a project's work as cards that move left to right — from backlog to done — so everyone can see what's in flight and what's stuck. | `kanban-board` |

### Content creation

Plan videos, posts and channels, and keep a calendar of what goes out.

| Template | Use it when | Slug |
|---|---|---|
| [YouTube channel plan](content-creation/youtube-channel-plan.yaml) | Starting a YouTube channel or resetting one — what it's about, who it's for, the kinds of videos it makes and the goals you'll measure it by. | `youtube-channel-plan` |
| [YouTube equipment checklist](content-creation/youtube-equipment-checklist.yaml) | Working out the gear for a YouTube setup or a shoot day — what you have, what you need, what to buy first and what to pack. | `youtube-equipment-checklist` |
| [YouTube script](content-creation/youtube-script.yaml) | Writing a YouTube video chapter by chapter — the hook, the talking points, what's on screen and the timestamps — so you stay on track while filming and editing. | `youtube-script` |
| [YouTube video brainstorming](content-creation/youtube-video-brainstorm.yaml) | Turning a rough idea for a YouTube video into something specific — the angle, the title, the thumbnail and the references — before you commit to making it. | `youtube-video-brainstorm` |
| [YouTube video plan](content-creation/youtube-video-plan.yaml) | Planning one YouTube video end to end — the idea, the research, the script, the shoot, the edit and the upload — with the tasks to get it out. | `youtube-video-plan` |
| [YouTube video research](content-creation/youtube-video-research.yaml) | Gathering what you need to know before making a YouTube video — sources, facts, quotes, visuals and the gaps — so the video holds up. | `youtube-video-research` |
| [YouTube video schedule](content-creation/youtube-schedule.yaml) | Keeping a YouTube channel on a steady posting rhythm — what's coming out each week, what's in production, and where to announce each video when it goes live. | `youtube-schedule` |

### Podcasting

Shape a show, research and outline episodes, and run the production schedule.

| Template | Use it when | Slug |
|---|---|---|
| [Podcast episode plan](podcasting/podcast-episode-plan.yaml) | Planning one episode from the first idea to publishing — ideas, research and outline in one place, with the production checklist beside them. | `podcast-episode-plan` |
| [Podcast outline](podcasting/podcast-outline.yaml) | Arranging an episode's topics and talking points into an order that flows, as cue cards you can glance at while you record. | `podcast-outline` |
| [Podcast research](podcasting/podcast-research.yaml) | Gathering what you know and what you find about an episode's topic or guest — notes, sources, quotes, clips and images — side by side. | `podcast-research` |
| [Podcast schedule](podcasting/podcast-schedule.yaml) | Running a show with several episodes on the go at once — seeing where each one is, from idea to published, and where the gaps are. | `podcast-schedule` |
| [Podcast script](podcasting/podcast-script.yaml) | Scripting an episode you'll read from — the timing, the order of segments and the narration — so it stays on track when the mic is on. | `podcast-script` |
| [Podcast show plan](podcasting/how-to-start-a-podcast.yaml) | Starting a podcast — settling the concept, the format, who it's for and how it reaches them before the first episode is recorded. | `how-to-start-a-podcast` |

### Storyboards

Plan a sequence shot by shot before anything is filmed or animated.

| Template | Use it when | Slug |
|---|---|---|
| [Animation storyboard](storyboards/animation-storyboard.yaml) | Turning a script into an animation plan scene by scene — the frames, the motion, the timing and the sound — before anyone opens an animation tool. | `animation-storyboard` |
| [App storyboard](storyboards/app-storyboard.yaml) | Mapping how someone moves through a mobile app — screen by screen, from launch to checkout — so the team can see the flow before it's designed in detail. | `app-storyboard` |
| [Fashion storyboard](storyboards/fashion-storyboard.yaml) | Showing how a collection comes together — the story behind it, the palette and fabrics, every look, and how it's styled, shot and shown in store. | `fashion-storyboard` |
| [Podcast storyboard](storyboards/podcast-storyboard.yaml) | Laying out the shape of an episode — open, intro, interview, breaks and close — with the research, questions and audio each part needs. | `podcast-storyboard` |
| [TVC advertising storyboard](storyboards/tvc-advertising-storyboard.yaml) | Pitching or planning a TV or online commercial, frame by frame against the clock, so every second earns its place and the must-have shots are covered. | `tvc-advertising-storyboard` |
| [UX storyboard](storyboards/ux-storyboard.yaml) | Sketching how one person moves through a website or app to get something done — what they do, what they feel, where it breaks — before designing screens. | `ux-storyboard` |
| [Video storyboard](storyboards/video-storyboard.yaml) | Planning a video scene by scene before the shoot — the shots, the people, the props, the lines and the camera — so the day runs to plan and nothing gets reshot. | `video-storyboard` |
| *[Event storyboard](events/event-storyboard.yaml)* | Walking through an event in the order guests and crew will live it — bump-in to bump-out — so the moving parts and the gaps show up before the day. | `event-storyboard` |
| *[Film storyboard](filmmaking/filmmaking-storyboard.yaml)* | Seeing a film scene by scene before the shoot — a frame for each key moment, with the action, the camera and the sound written under it. | `filmmaking-storyboard` |
| *[Game design storyboard](game-design/game-design-storyboard.yaml)* | Laying out a game's key scenes panel by panel — what the player sees, what they do, where the camera goes — before it's built. | `game-design-storyboard` |
| *[Motion design storyboard](motion-design/motion-design-storyboard.yaml)* | Laying out an animated sequence frame by frame — the key moments, how each one moves into the next, and what the voice-over and sound do. | `motion-design-storyboard` |
| *[Photography storyboard](photography/photography-storyboard.yaml)* | Planning a shoot set-up by set-up — the scene, the light, the camera and the feeling of each image — so the day stays on track and the set looks consistent. | `photography-storyboard` |

### Filmmaking

From treatment and script to shot lists and the shoot itself.

| Template | Use it when | Slug |
|---|---|---|
| [Beat sheet](filmmaking/beat-sheet.yaml) | Shaping a screenplay into the fifteen classic story beats before you write scenes, so the pacing and the arc are settled first. | `beat-sheet` |
| [Film brainstorming](filmmaking/film-brainstorm.yaml) | Turning a rough film idea into a wall of options — characters, places, looks and history — then picking the ones that make the story better. | `film-brainstorm` |
| [Film call sheet](filmmaking/call-sheet.yaml) | Getting a shoot day's cast and crew to the right place at the right time — the job, the location, who's on, what to bring and the run of the day. | `call-sheet` |
| [Film equipment checklist](filmmaking/film-equipment-checklist.yaml) | Packing for a shoot, one day or several, so every camera, light, mic, cable and battery is on set when it's needed. | `film-equipment-checklist` |
| [Film location scouting](filmmaking/film-location-scouting.yaml) | Finding and vetting the places you'll film — what the script needs, every candidate you visit, and the light, power, access and permits at each. | `film-location-scouting` |
| [Film marketing plan](filmmaking/film-marketing-plan.yaml) | Launching a finished film — who it's for, what success looks like, the assets, and the push before, at and after release. | `film-marketing-plan` |
| [Film moodboard](filmmaking/filmmaking-moodboard.yaml) | Setting the look and feel of a film for cast and crew — light, colour, sets, wardrobe and framing — in images before anyone builds or shoots. | `filmmaking-moodboard` |
| [Film pre-production](filmmaking/pre-production-plan.yaml) | Running a film's whole pre-production from one hub — the ideas, the look, the storyboard, the shot list and the call sheet, with the workflow and gear checklists beside them. | `pre-production-plan` |
| [Film shot list](filmmaking/shot-list-film.yaml) | Listing every shot you need, scene by scene, with size, angle and movement, so nothing critical is missed on the day. | `shot-list-film` |
| [Film storyboard](filmmaking/filmmaking-storyboard.yaml) | Seeing a film scene by scene before the shoot — a frame for each key moment, with the action, the camera and the sound written under it. | `filmmaking-storyboard` |
| [One day doc](filmmaking/one-day-doc.yaml) | Planning a short documentary you'll shoot in a single day — the subject, the interview, the shots you need and an hour-by-hour plan. | `one-day-doc` |

### Creative writing

Worlds, characters and scenes for stories of any length.

| Template | Use it when | Slug |
|---|---|---|
| [Character design moodboard](creative-writing/character-design-moodboard.yaml) | Finding what a character looks like and lives among — face, clothes, the things they love, the places they go — before you describe them on the page. | `character-design-moodboard` |
| [Character profile](creative-writing/character-profile.yaml) | Getting to know one character well enough to write them — who they are, where they've been, what they want and what gets in their way. | `character-profile` |
| [Character relationship map](creative-writing/character-relationship-map.yaml) | Seeing the whole cast at once — who sits at the centre, who orbits them, and what each pair wants from each other — so the tension between them is planned, not accidental. | `character-relationship-map` |
| [Hero's journey](creative-writing/heros-journey.yaml) | Plotting a protagonist's adventure through the classic twelve stages — leaving home, being tested, coming back changed — and checking the sequence holds. | `heros-journey` |
| [Novel marketing plan](creative-writing/novel-marketing-plan.yaml) | Launching a book — who it's for, what success looks like, the build-up before release, launch week and keeping it alive afterwards. | `novel-marketing-plan` |
| [Novel moodboard](creative-writing/novel-moodboard.yaml) | Collecting the images, colours, clips and textures that hold the feeling of your story, so you can return to it every time you sit down to write. | `novel-moodboard` |
| [Novel plan](creative-writing/novel-plan.yaml) | Running a whole novel from one board — the idea, research, inspiration, characters and outline each in their own board, with the checklists that take it from first draft to print. | `novel-plan` |
| [Research](creative-writing/novel-research.yaml) | Gathering what you need to know for a story — facts you already hold, articles, quotes, clips and images — so the world on the page rings true. | `novel-research` |
| [Story arc](creative-writing/story-arc.yaml) | Laying your plot points along the rise and fall of a story — the opening, the build, the peak and the way down — to see whether the tension climbs where it should. | `story-arc` |
| [Story brainstorm](creative-writing/story-brainstorm.yaml) | Turning a spark of a story into a pile of ideas — the central concept, its themes, everything it suggests — and then picking the ones worth writing. | `story-brainstorm` |
| [Story map](creative-writing/story-map.yaml) | Testing a story idea against five basic questions — who, where, what's wrong, what's at stake and how it ends — before you outline. | `story-map` |
| [Story outline](creative-writing/story-outline.yaml) | Outlining a story in five acts — the key scenes, a line on each, moved around until the sequence and pacing work — before you start the draft. | `story-outline` |
| [Three act structure](creative-writing/three-act-structure-outline.yaml) | Planning a story in three acts — setup, confrontation, resolution — with the plot points that hinge each act into the next. | `three-act-structure-outline` |
| [World building](creative-writing/world-building.yaml) | Inventing the world a story happens in — its land, climate, places and peoples, their history and the rules they live by — before the characters move in. | `world-building` |

### Novel outlines

Structure a book — plot, chapters and the people in it.

| Template | Use it when | Slug |
|---|---|---|
| *[Hero's journey](creative-writing/heros-journey.yaml)* | Plotting a protagonist's adventure through the classic twelve stages — leaving home, being tested, coming back changed — and checking the sequence holds. | `heros-journey` |
| *[Story arc](creative-writing/story-arc.yaml)* | Laying your plot points along the rise and fall of a story — the opening, the build, the peak and the way down — to see whether the tension climbs where it should. | `story-arc` |
| *[Story map](creative-writing/story-map.yaml)* | Testing a story idea against five basic questions — who, where, what's wrong, what's at stake and how it ends — before you outline. | `story-map` |
| *[Story outline](creative-writing/story-outline.yaml)* | Outlining a story in five acts — the key scenes, a line on each, moved around until the sequence and pacing work — before you start the draft. | `story-outline` |
| *[Three act structure](creative-writing/three-act-structure-outline.yaml)* | Planning a story in three acts — setup, confrontation, resolution — with the plot points that hinge each act into the next. | `three-act-structure-outline` |

### Photography

Plan shoots, shot lists and the look you're after.

| Template | Use it when | Slug |
|---|---|---|
| [Model brief](photography/model-brief.yaml) | Briefing a model agency on a campaign so they can put forward the right people and everyone arrives knowing the look, the shots and the terms. | `model-brief` |
| [Photography contact sheet](photography/contact-sheet.yaml) | Narrowing a shoot down to a shortlist so the client can choose the finals before anything gets retouched. | `contact-sheet` |
| [Photography moodboard](photography/photography-moodboard.yaml) | Setting the look of a shoot before it happens — the light, the framing, the colour — so photographer, crew and client picture the same images. | `photography-moodboard` |
| [Photography storyboard](photography/photography-storyboard.yaml) | Planning a shoot set-up by set-up — the scene, the light, the camera and the feeling of each image — so the day stays on track and the set looks consistent. | `photography-storyboard` |
| [Photography workflow](photography/photography-workflow.yaml) | Running a commercial or client shoot from first enquiry to final delivery, so every job moves through the same steps and nothing gets skipped. | `photography-workflow` |
| [Photoshoot brief](photography/photoshoot-brief.yaml) | Briefing a photographer and their team on a shoot — the client, the subject, the goals and every deliverable — so the images land on the first try. | `photoshoot-brief` |
| [Photoshoot call sheet](photography/photoshoot-call-sheet.yaml) | Getting crew and talent to the right place at the right time on shoot day — who's coming, where, when, and what they need to bring. | `photoshoot-call-sheet` |
| [Photoshoot plan](photography/photoshoot-plan.yaml) | Running a whole shoot from one place — the brief, the moodboard, the shot list, the call sheet and the selects each get a board, with the workflow and gear checklists beside them. | `photoshoot-plan` |
| [Photoshoot shot list](photography/shot-list-photoshoot.yaml) | Listing every photo you need from a shoot, subject by subject, so the critical one doesn't get missed on the day. | `shot-list-photoshoot` |
| [Travel photography plan](photography/travel-photography.yaml) | Planning a photo trip — where you're going, how you'll get around, what you want to shoot at each stop and what goes in the bag. | `travel-photography` |

### Marketing strategy

Audience, positioning, channels and the plan that ties them together.

| Template | Use it when | Slug |
|---|---|---|
| [Market research](marketing-strategy/market-research.yaml) | Building a picture of a market before a brand, a launch or a rebrand — the competitors, the customers, the trends and where there's room for you. | `market-research` |
| [Marketing plan](marketing-strategy/marketing-plan.yaml) | Setting out how a business will market itself — the brand, the audience, the goals, the channels and the budget — in one plan the team can follow and check against. | `marketing-plan` |
| [Target audience](marketing-strategy/target-audience.yaml) | Working out who a product or service is for, by writing up the main audience segments as personas the whole team can design for. | `target-audience` |
| *[Brand positioning map](logo-design/brand-positioning-map.yaml)* | Placing your brand against its competitors on two axes to find the open ground — before a new logo or a rebrand. | `brand-positioning-map` |
| *[Customer persona](ux-design/persona.yaml)* | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |

### Marketing campaigns

Plan one campaign — the idea, the assets, the schedule and the results.

| Template | Use it when | Slug |
|---|---|---|
| [Campaign plan](marketing-campaign/campaign-plan.yaml) | Turning an approved brief into a campaign you can run — the background, the goals and deliverables, the budget, the timeline and the creative direction. | `campaign-plan` |
| [Campaign reports](marketing-campaign/campaign-reports.yaml) | Wrapping up a campaign — what it set out to do, how each channel performed, what it cost and returned, and what to carry into the next one. | `campaign-reports` |
| [Campaign strategy](marketing-campaign/campaign-strategy.yaml) | Deciding the shape of a campaign before any work starts — the objective, who it's for, what you'll say, where you'll say it and over how long. | `campaign-strategy` |
| [Marketing assets](marketing-campaign/marketing-assets.yaml) | Keeping every brand asset a campaign team needs in one place — logos, colours, type, layouts and the photo and illustration style — so nobody hunts through folders. | `marketing-assets` |
| [Marketing brief](marketing-campaign/marketing-brief.yaml) | Starting a marketing campaign with the client or team — the background, goals, brand, audience and the numbers it'll be judged on — written down before the work starts. | `marketing-brief` |
| [Marketing calendar](marketing-campaign/calendar.yaml) | Laying out a month of marketing on one board — the dates that matter, what goes out each week on which channel, and what has to be ready before it does. | `calendar` |
| [Marketing campaign moodboard](marketing-campaign/marketing-campaign-moodboard.yaml) | Setting the look of a campaign before design starts — the colours, type, imagery and branding cues it should share, pinned up where everyone can see them. | `marketing-campaign-moodboard` |
| [Marketing content plan](marketing-campaign/marketing-content-plan.yaml) | Planning the written and visual content for a campaign — the pillars, every piece and its channel, and each one moving from idea to published. | `marketing-content-plan` |
| [Social media calendar](marketing-campaign/social-media-calendar.yaml) | Planning a week of social posts ahead of time — a backlog of ideas, what goes out each day on which platform, the copy and artwork, and a review before it's scheduled. | `social-media-calendar` |

### Brand strategy

Define what a brand stands for and how it looks, sounds and behaves.

| Template | Use it when | Slug |
|---|---|---|
| [Brand audit](branding/brand-audit.yaml) | Taking stock of an existing brand before a rebrand — its audience, place in the market, visuals, values and messaging — and deciding what to keep, fix or drop. | `brand-audit` |
| [Brand naming](branding/brand-naming.yaml) | Coming up with a name for a company, product or product line — from the criteria, through word banks and a long list, to a shortlist you've tested. | `brand-naming` |
| [Brand personality](branding/brand-personality.yaml) | Describing a brand as if it were a person — the traits it has, where it sits on each scale, and what it would never do — so later choices about name, look and voice have something to check against. | `brand-personality` |
| [Brand strategy](branding/brand-strategy.yaml) | Running a brand strategy project in one place — research, audience, positioning, personality and visual direction — with a board for each part. | `brand-strategy` |
| [Brand SWOT analysis](branding/brand-swot-analysis.yaml) | Sizing up a brand — its internal strengths and weaknesses and the outside opportunities and threats — before a rebrand or a new strategy. | `brand-swot-analysis` |
| *[Brand positioning map](logo-design/brand-positioning-map.yaml)* | Placing your brand against its competitors on two axes to find the open ground — before a new logo or a rebrand. | `brand-positioning-map` |
| *[Customer persona](ux-design/persona.yaml)* | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |
| *[Logo design brief](logo-design/logo-design-creative-brief.yaml)* | Writing the brief for a new logo — purpose, personality, audience, where it'll be used and what the client likes — so the designer starts with everything. | `logo-design-creative-brief` |
| *[Logo moodboard](logo-design/logo-moodboard.yaml)* | Exploring the visual direction for a logo — references, imagery, colour, type and pattern — and getting it agreed before you draw. | `logo-moodboard` |
| *[Market research](marketing-strategy/market-research.yaml)* | Building a picture of a market before a brand, a launch or a rebrand — the competitors, the customers, the trends and where there's room for you. | `market-research` |

### Brand workshops

Run a brand workshop with a team or a client, exercise by exercise.

| Template | Use it when | Slug |
|---|---|---|
| *[Brand naming](branding/brand-naming.yaml)* | Coming up with a name for a company, product or product line — from the criteria, through word banks and a long list, to a shortlist you've tested. | `brand-naming` |
| *[Brand personality](branding/brand-personality.yaml)* | Describing a brand as if it were a person — the traits it has, where it sits on each scale, and what it would never do — so later choices about name, look and voice have something to check against. | `brand-personality` |
| *[Brand positioning map](logo-design/brand-positioning-map.yaml)* | Placing your brand against its competitors on two axes to find the open ground — before a new logo or a rebrand. | `brand-positioning-map` |
| *[Brand SWOT analysis](branding/brand-swot-analysis.yaml)* | Sizing up a brand — its internal strengths and weaknesses and the outside opportunities and threats — before a rebrand or a new strategy. | `brand-swot-analysis` |
| *[Customer persona](ux-design/persona.yaml)* | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |
| *[Logo design brief](logo-design/logo-design-creative-brief.yaml)* | Writing the brief for a new logo — purpose, personality, audience, where it'll be used and what the client likes — so the designer starts with everything. | `logo-design-creative-brief` |
| *[Logo moodboard](logo-design/logo-moodboard.yaml)* | Exploring the visual direction for a logo — references, imagery, colour, type and pattern — and getting it agreed before you draw. | `logo-moodboard` |

### Market research

Size a market, map competitors and gather what customers say.

| Template | Use it when | Slug |
|---|---|---|
| [Day in the life of](market-research/day-in-the-life-of.yaml) | Mapping one customer's ordinary day hour by hour — what they do, use and feel — to see where your product or service fits in, or could. | `day-in-the-life-of` |
| *[Brand positioning map](logo-design/brand-positioning-map.yaml)* | Placing your brand against its competitors on two axes to find the open ground — before a new logo or a rebrand. | `brand-positioning-map` |
| *[Brand SWOT analysis](branding/brand-swot-analysis.yaml)* | Sizing up a brand — its internal strengths and weaknesses and the outside opportunities and threats — before a rebrand or a new strategy. | `brand-swot-analysis` |
| *[Customer persona](ux-design/persona.yaml)* | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |
| *[Diary study](ux-research/diary-study.yaml)* | Running a diary study — participants log their habits and experiences over days or weeks — and turning the entries into insights about how people really use a product. | `diary-study` |
| *[Logo moodboard](logo-design/logo-moodboard.yaml)* | Exploring the visual direction for a logo — references, imagery, colour, type and pattern — and getting it agreed before you draw. | `logo-moodboard` |
| *[Market research](marketing-strategy/market-research.yaml)* | Building a picture of a market before a brand, a launch or a rebrand — the competitors, the customers, the trends and where there's room for you. | `market-research` |
| *[Market research brief](creative-briefs/market-research-brief.yaml)* | Briefing a research study so the researcher can pick the right method — the decision it informs, who to study, and what's already known. | `market-research-brief` |

### Strategy & management

Plan direction, run planning sessions and make decisions in the open.

| Template | Use it when | Slug |
|---|---|---|
| [Competitor landscape](strategy/competitor-landscape.yaml) | Mapping everyone in your market on two axes, so you can see the whole category at a glance and where you fit in it. | `competitor-landscape` |
| [Empathy map](strategy/empathy-map.yaml) | Stepping into one customer's shoes — what they think, see, say and hear — to find what hurts and what they stand to gain. | `empathy-map` |
| [Porter's five forces](strategy/porters-five-forces.yaml) | Judging how attractive an industry is by weighing the five pressures on its profits — rivals, newcomers, suppliers, buyers and substitutes. | `porters-five-forces` |
| [Stakeholder map](strategy/stakeholder-mapping.yaml) | Sorting the people around a project by how much power they hold and how much they care, so you know who to keep close and who to keep informed. | `stakeholder-mapping` |
| [Team structure](strategy/team-structure.yaml) | Laying out who's on the team, what each person owns and who reports to whom — to plan growth or introduce new people. | `team-structure` |
| *[Value proposition canvas](startups/value-proposition-canvas.yaml)* | Checking a product fits its customer — the jobs, pains and gains on one side, the features, pain relievers and gain creators on the other — and finding where they don't line up. | `value-proposition-canvas` |

### Product management

Roadmaps, specs, prioritisation and launches.

| Template | Use it when | Slug |
|---|---|---|
| [Customer journey map](product-management/customer-journey-map.yaml) | Walking through a customer's experience stage by stage — what they do, think and feel, where it hurts — to find what to fix or build next. | `customer-journey-map` |
| [Kanban board](product-management/kanban-board.yaml) | Running a project's work as cards that move left to right — from backlog to done — so everyone can see what's in flight and what's stuck. | `kanban-board` |
| [Product hub](product-management/product-hub.yaml) | Running a product from one place — the strategy, roadmap, research, designs and launches each on their own board, with the overview on top. | `product-hub` |
| [Product launch plan](product-management/product-launch-plan.yaml) | Planning a product launch — the goals, the story you'll tell, the channels, the assets and copy each needs, and the run-up to launch day. | `product-launch-plan` |
| [Product roadmap](product-management/product-roadmap.yaml) | Planning what a product team builds next — a backlog of ideas, the features being specced, estimated and built, and the order they ship in. | `product-roadmap` |
| [Project retrospective](product-management/project-retrospective.yaml) | Looking back at a finished project with the team — what went well, what didn't, what you learned — and leaving with a short list of changes. | `project-retrospective` |
| [User story](product-management/user-story.yaml) | Writing up agile user stories for a feature — who wants it, what they need and why, how you'll know it's done, and where each story is in the sprint. | `user-story` |

### UX research

Plan research, run interviews and turn findings into insight.

| Template | Use it when | Slug |
|---|---|---|
| [Diary study](ux-research/diary-study.yaml) | Running a diary study — participants log their habits and experiences over days or weeks — and turning the entries into insights about how people really use a product. | `diary-study` |
| *[Customer persona](ux-design/persona.yaml)* | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |
| *[Usability report](ux-design/usability-report.yaml)* | Turning a round of usability testing into findings a team will act on — what you tested, what broke, the quotes and clips that prove it, and what to fix first. | `usability-report` |
| *[Usability testing plan](ux-design/usability-testing-plan.yaml)* | Setting up a usability study — why you're testing, who with, the tasks and sessions, and how you'll measure what happened — so the team agrees before anyone books a participant. | `usability-testing-plan` |
| *[User flow diagram](ux-design/user-flow.yaml)* | Mapping the steps a person takes through your product to reach a goal — where they come in, each screen and decision, where they get stuck — so you can see what to change. | `user-flow` |
| *[User interview notes](ux-design/user-interview-notes.yaml)* | Capturing one customer interview as it happens — who they are, what they said, what you saw — and sorting it into needs, pains and themes the team can use. | `user-interview-notes` |
| *[UX research brief](creative-briefs/ux-research-brief.yaml)* | Setting up a user research project — what you need to learn, from whom, by which method, and what's already known. | `ux-research-brief` |
| *[UX storyboard](storyboards/ux-storyboard.yaml)* | Sketching how one person moves through a website or app to get something done — what they do, what they feel, where it breaks — before designing screens. | `ux-storyboard` |

### UX design

Flows, wireframes and the thinking behind an interface.

| Template | Use it when | Slug |
|---|---|---|
| [Customer persona](ux-design/persona.yaml) | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |
| [Site map](ux-design/site-map.yaml) | Planning a website's structure and content together — every page as its own board, with rough copy, images and a layout sketch inside it. | `site-map` |
| [Usability report](ux-design/usability-report.yaml) | Turning a round of usability testing into findings a team will act on — what you tested, what broke, the quotes and clips that prove it, and what to fix first. | `usability-report` |
| [Usability testing plan](ux-design/usability-testing-plan.yaml) | Setting up a usability study — why you're testing, who with, the tasks and sessions, and how you'll measure what happened — so the team agrees before anyone books a participant. | `usability-testing-plan` |
| [User flow diagram](ux-design/user-flow.yaml) | Mapping the steps a person takes through your product to reach a goal — where they come in, each screen and decision, where they get stuck — so you can see what to change. | `user-flow` |
| [User interview notes](ux-design/user-interview-notes.yaml) | Capturing one customer interview as it happens — who they are, what they said, what you saw — and sorting it into needs, pains and themes the team can use. | `user-interview-notes` |
| *[UX storyboard](storyboards/ux-storyboard.yaml)* | Sketching how one person moves through a website or app to get something done — what they do, what they feel, where it breaks — before designing screens. | `ux-storyboard` |
| *[Web design moodboard](moodboards/web-design-moodboard.yaml)* | Setting the visual direction for a website — look, layout, interface pieces and motion — so everyone agrees on it before design starts. | `web-design-moodboard` |
| *[Website design brief](creative-briefs/website-design-brief.yaml)* | Briefing a website build before anyone writes code — why it's happening, what success looks like, who it's for and how the brand should come through. | `website-design-brief` |
| *[Website ideas](website-design/website-ideas.yaml)* | Brainstorming a new website with the team — how it could look, what it could do and how visitors should feel — before anything is decided. | `website-ideas` |
| *[Website plan](website-design/website-plan.yaml)* | Running a website project from one hub — brief, audience, visual direction, sitemap and content — with the checklists that move it from plan to launch. | `website-plan` |

### Website design

Plan a site's structure, content and look.

| Template | Use it when | Slug |
|---|---|---|
| [Website competitor analysis](website-design/website-competitor-analysis.yaml) | Comparing competitors' websites — how they look, what they say, how they're found and how they work — to decide where yours will stand out. | `website-competitor-analysis` |
| [Website content](website-design/website-content.yaml) | Planning a website's words, images and layout one page at a time, so the team can see each page before anyone designs or builds it. | `website-content` |
| [Website ideas](website-design/website-ideas.yaml) | Brainstorming a new website with the team — how it could look, what it could do and how visitors should feel — before anything is decided. | `website-ideas` |
| [Website plan](website-design/website-plan.yaml) | Running a website project from one hub — brief, audience, visual direction, sitemap and content — with the checklists that move it from plan to launch. | `website-plan` |
| *[Customer persona](ux-design/persona.yaml)* | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |
| *[Site map](ux-design/site-map.yaml)* | Planning a website's structure and content together — every page as its own board, with rough copy, images and a layout sketch inside it. | `site-map` |
| *[Web design moodboard](moodboards/web-design-moodboard.yaml)* | Setting the visual direction for a website — look, layout, interface pieces and motion — so everyone agrees on it before design starts. | `web-design-moodboard` |
| *[Website design brief](creative-briefs/website-design-brief.yaml)* | Briefing a website build before anyone writes code — why it's happening, what success looks like, who it's for and how the brand should come through. | `website-design-brief` |

### Software development

Plan features, sprints, architecture and releases.

| Template | Use it when | Slug |
|---|---|---|
| [Agile task board](software-development/agile-task-board.yaml) | Running a sprint — the goal, the backlog, and every task moving from to-do through review to done where the whole team can see it. | `agile-task-board` |
| [Technical architecture](software-development/technical-architecture.yaml) | Laying out how a system is built — the pieces, the stack, the outside services and the decisions behind them — so the whole team shares one picture. | `technical-architecture` |
| *[Flow chart](brainstorming/flow-chart.yaml)* | Mapping a workflow or decision process step by step, so you can see where it branches, stalls or could be simpler. | `flow-chart` |
| *[Project retrospective](product-management/project-retrospective.yaml)* | Looking back at a finished project with the team — what went well, what didn't, what you learned — and leaving with a short list of changes. | `project-retrospective` |

### Graphic design

Briefs, concepts and presentation for design projects.

| Template | Use it when | Slug |
|---|---|---|
| [Brand assets](graphic-design/brand-assets.yaml) | Keeping a brand's logos, colours, type, imagery and rules in one place so everyone making work for it uses the right files. | `brand-assets` |
| [Design brief](graphic-design/design-brief.yaml) | Agreeing on a design job with a client before the work starts — the project, the goals, the audience, budget and timeline, examples, and what to avoid. | `design-brief` |
| [Graphic design moodboard](graphic-design/graphic-design-moodboard.yaml) | Setting the visual direction for a design project — imagery, colour, type, texture and layout — from existing references before you design anything new. | `graphic-design-moodboard` |
| [Graphic design project plan](graphic-design/graphic-design-project-plan.yaml) | Running a design project from brief to final files — the brief, research, concepts, development and delivery — with the dates and tasks in one place. | `graphic-design-project-plan` |
| *[Brainstorming workshop](brainstorming/brainstorming-workshop.yaml)* | Running a brainstorm with a group — framing the question, getting ideas out fast, clustering them and leaving with a few to pursue. | `brainstorming-workshop` |
| *[Brand strategy](branding/brand-strategy.yaml)* | Running a brand strategy project in one place — research, audience, positioning, personality and visual direction — with a board for each part. | `brand-strategy` |
| *[Customer persona](ux-design/persona.yaml)* | Turning research about real customers into one person the whole team can picture — who they are, what they need, what frustrates them and what a great experience would feel like. | `persona` |
| *[Logo design presentation](logo-design/logo-design-presentation.yaml)* | Presenting two or three logo concepts so the client sees each one in use, follows the thinking, and settles on a direction. | `logo-design-presentation` |
| *[Site map](ux-design/site-map.yaml)* | Planning a website's structure and content together — every page as its own board, with rough copy, images and a layout sketch inside it. | `site-map` |
| *[Website content](website-design/website-content.yaml)* | Planning a website's words, images and layout one page at a time, so the team can see each page before anyone designs or builds it. | `website-content` |

### Logo design

From research and sketches to the final mark.

| Template | Use it when | Slug |
|---|---|---|
| [Brand positioning map](logo-design/brand-positioning-map.yaml) | Placing your brand against its competitors on two axes to find the open ground — before a new logo or a rebrand. | `brand-positioning-map` |
| [Logo brainstorming](logo-design/logo-brainstorm.yaml) | Generating a wide spread of logo ideas — words, symbols, images and sketches — before narrowing to a few directions. | `logo-brainstorm` |
| [Logo design assets handover](logo-design/logo-design-assets-handover.yaml) | Handing a finished logo to the client — every file, colour, font and rule in one place they can still find a year from now. | `logo-design-assets-handover` |
| [Logo design brief](logo-design/logo-design-creative-brief.yaml) | Writing the brief for a new logo — purpose, personality, audience, where it'll be used and what the client likes — so the designer starts with everything. | `logo-design-creative-brief` |
| [Logo design presentation](logo-design/logo-design-presentation.yaml) | Presenting two or three logo concepts so the client sees each one in use, follows the thinking, and settles on a direction. | `logo-design-presentation` |
| [Logo design project plan](logo-design/logo-design-plan.yaml) | Running a whole logo project from one hub — brief, brainstorm, research, moodboard, concepts and handover — with the workflow checklists beside them. | `logo-design-plan` |
| [Logo moodboard](logo-design/logo-moodboard.yaml) | Exploring the visual direction for a logo — references, imagery, colour, type and pattern — and getting it agreed before you draw. | `logo-moodboard` |

### Motion design

Plan animation — style, boards and the sequence of moves.

| Template | Use it when | Slug |
|---|---|---|
| [Motion design brainstorming](motion-design/motion-brainstorming.yaml) | Turning the message an animation has to carry into lots of possible treatments — characters, styles, metaphors — then choosing the few worth designing. | `motion-brainstorming` |
| [Motion design brief](motion-design/motion-design-brief.yaml) | Agreeing with a client what an animation is for, what it must say, who it's for and exactly what gets delivered, before a frame is designed. | `motion-design-brief` |
| [Motion design moodboard](motion-design/motion-design-moodboard.yaml) | Setting the visual and animation direction for a motion piece — characters, type, colour, and real examples of how things should move and sound. | `motion-design-moodboard` |
| [Motion design project plan](motion-design/motion-design-plan.yaml) | Running a motion design job from one hub — brief, ideas, moodboard, storyboard and style frames — with the workflow checklist beside them. | `motion-design-plan` |
| [Motion design storyboard](motion-design/motion-design-storyboard.yaml) | Laying out an animated sequence frame by frame — the key moments, how each one moves into the next, and what the voice-over and sound do. | `motion-design-storyboard` |
| [Motion design style frames](motion-design/style-frames.yaml) | Presenting two or three visual directions for the same scene so the team or client can choose one look before animation starts. | `style-frames` |

### Game design

Concept, mechanics, worlds and characters for a game.

| Template | Use it when | Slug |
|---|---|---|
| [Game character profile](game-design/game-character-profile.yaml) | Building one character for a game — who they are, where they came from, how they look and how they move — so artists, animators and designers all work from the same person. | `game-character-profile` |
| [Game character relationship map](game-design/game-character-relationship-map.yaml) | Working out who's who in a game's cast — who's on whose side, who owes whom, and which ties carry the story. | `game-character-relationship-map` |
| [Game design brainstorming](game-design/game-design-brainstorm.yaml) | Turning a rough game idea into a wall of possibilities — characters, story, play, places and look — then picking the ones worth building. | `game-design-brainstorm` |
| [Game design document](game-design/game-design-document.yaml) | Running a whole game project from one hub — the vision, the brainstorm, the look, the world, the levels, the characters and the launch — instead of a long document nobody reads. | `game-design-document` |
| [Game design flow diagram](game-design/game-design-flow-diagram.yaml) | Mapping every screen a player passes through — title, menus, levels, pause, scoreboard, credits — so the team can see how the whole game connects. | `game-design-flow-diagram` |
| [Game design moodboard](game-design/game-design-moodboard.yaml) | Setting the look and feel of a game — characters, places, textures, colour, motion and sound — so the team shares one picture of it before production. | `game-design-moodboard` |
| [Game design story outline](game-design/game-story-outline.yaml) | Shaping a game's plot into a beginning, middle and end — and lining each story beat up with what the player is doing at that point. | `game-story-outline` |
| [Game design storyboard](game-design/game-design-storyboard.yaml) | Laying out a game's key scenes panel by panel — what the player sees, what they do, where the camera goes — before it's built. | `game-design-storyboard` |
| [Game level design](game-design/level-design.yaml) | Planning one level of a game — the concept, the map, the route through it, the challenges and rewards — before any of it is built. | `level-design` |
| [Game marketing plan](game-design/game-marketing-plan.yaml) | Planning a game's launch from the first announcement to the months after release — who it's for, the budget, and what happens in each phase. | `game-marketing-plan` |
| [Game mechanics](game-design/game-design-mechanics.yaml) | Writing down the rules of a game — how the player moves, what they can do, how scoring works and how they progress — before anyone starts tuning numbers. | `game-design-mechanics` |
| [Game worldbuilding](game-design/game-world-building.yaml) | Building the world a game takes place in — the land, who lives there and how they live — so characters and levels have rules to grow from. | `game-world-building` |

### Visual art

Develop a series, plan a piece and keep a studio practice going.

| Template | Use it when | Slug |
|---|---|---|
| [Visual art brainstorming](visual-art/visual-art-brainstorm.yaml) | Turning a first idea for a piece into something of your own — getting every thought, sketch and reference out of your head and onto the board, then picking a direction. | `visual-art-brainstorm` |
| [Visual art brief](visual-art/visual-art-brief.yaml) | Starting a commission or a personal piece with a brief — what you're making, who it's for, the references, your own goals and exactly what you'll hand over. | `visual-art-brief` |
| [Visual art moodboard](visual-art/visual-art-moodboard.yaml) | Collecting the inspiration for a piece — images, colours, textures and themes — and shaping them into a look you can work from. | `visual-art-moodboard` |
| [Visual art project plan](visual-art/visual-art-project-plan.yaml) | Planning an art project from brief to finished piece — the brief, the ideas, the inspiration and research, and the steps and materials to make it — in one place. | `visual-art-project-plan` |
| [Visual art research](visual-art/visual-art-research.yaml) | Researching the subject of an artwork before you make it — the facts, the history, the way other artists have handled it — so the piece carries more meaning. | `visual-art-research` |

### Craft & making

Plan handmade projects, materials and the steps to make them.

| Template | Use it when | Slug |
|---|---|---|
| [Craft materials list](craft-and-making/craft-materials-list.yaml) | Gathering every supply a project needs before you start — what you have, what to buy, what it costs — and keeping stock if you sell what you make. | `craft-materials-list` |
| [Craft project brainstorm](craft-and-making/craft-brainstorm.yaml) | Turning a first idea for something you want to make into several directions worth trying, with sketches and pictures side by side. | `craft-brainstorm` |
| [Craft project moodboard](craft-and-making/craft-project-moodboard.yaml) | Settling the look of something you're making — the pictures, the colours, the materials and textures — before you cut or stitch anything. | `craft-project-moodboard` |
| [Craft project plan](craft-and-making/craft-project-plan.yaml) | Planning one thing you're making from idea to finished piece — what it's for, the inspiration, the materials and the steps — so it actually gets finished. | `craft-project-plan` |
| [Craft project timeline](craft-and-making/craft-project-timeline.yaml) | Scheduling a run of handmade products from design to sale, with a date on each stage so you have stock ready when buyers are. | `craft-project-timeline` |

### Fashion

Collections, lookbooks and the research behind them.

| Template | Use it when | Slug |
|---|---|---|
| [Fashion brainstorm](fashion/fashion-brainstorm.yaml) | Getting garment and collection ideas out fast — shapes, materials, colour, details and influences — then picking the threads worth developing. | `fashion-brainstorm` |
| [Fashion design brief](fashion/fashion-design-brief.yaml) | Agreeing what a fashion project needs to be before designing — the background, the wearer, the references, the goals and what gets delivered. | `fashion-design-brief` |
| [Fashion lookbook](fashion/fashion-lookbook.yaml) | Assembling a collection look by look — the model, the pieces, the styling — for a shoot, a lookbook or a runway show. | `fashion-lookbook` |
| [Fashion project plan](fashion/fashion-project-plan.yaml) | Running a fashion project from one hub — the brief, the brainstorm, the moodboard and the collection — with the tasks and dates beside them. | `fashion-project-plan` |
| *[Fashion moodboard](moodboards/fashion-moodboard.yaml)* | Setting the look for a collection, a shoot or a styling job — references, silhouettes, fabrics and palette — before anything gets made. | `fashion-moodboard` |

### Interior design

Rooms, materials, furniture and client presentations.

| Template | Use it when | Slug |
|---|---|---|
| [Interior design brief](interior-design/interior-design-brief.yaml) | Starting an interior project with a client — why it's happening, the rooms and requirements, who uses the space and the look they have in mind. | `interior-design-brief` |
| [Interior design moodboard](interior-design/interior-design-moodboard.yaml) | Setting the look of a room or venue — images, colours, materials and furniture together — so the client agrees on a direction before anything is bought. | `interior-design-moodboard` |
| [Interior design product list](interior-design/interior-design-product-list.yaml) | Keeping every product and material for an interior project on one list, by category, and ticking each off as it's bought. | `interior-design-product-list` |
| [Interior design project plan](interior-design/interior-design-plan.yaml) | Running a whole interior project in one place — the brief, the moodboard and the shopping list as boards, plus the checklists that get it from idea to installed. | `interior-design-plan` |

### Architecture

Site research, concepts and project presentation.

| Template | Use it when | Slug |
|---|---|---|
| [Architectural design concept](architecture/architecture-design-concept.yaml) | Presenting a building's design concept to a client or team — the idea, the site, the precedents, the drawings and renders, and the materials — in one place. | `architecture-design-concept` |
| [Architecture moodboard](architecture/architecture-moodboard.yaml) | Setting the look and atmosphere of a building project — form, materials, textures, light and colour — from collected images before the design is drawn. | `architecture-moodboard` |
| [Architecture project plan](architecture/architecture-project-plan.yaml) | Running an architecture project from one hub — the brief, the work at each design stage, the drawings, the moodboard and the team. | `architecture-project-plan` |
| *[Interior design brief](interior-design/interior-design-brief.yaml)* | Starting an interior project with a client — why it's happening, the rooms and requirements, who uses the space and the look they have in mind. | `interior-design-brief` |
| *[Interior design product list](interior-design/interior-design-product-list.yaml)* | Keeping every product and material for an interior project on one list, by category, and ticking each off as it's bought. | `interior-design-product-list` |

### Home renovation & DIY

Plan a renovation room by room — ideas, budget and the order of work.

| Template | Use it when | Slug |
|---|---|---|
| [Renovation design brief](diy-home-renovations/renovation-design-brief.yaml) | Writing down what a renovation has to achieve — the goals, the rooms, the budget, the timeline and the look — so everyone building it works to the same vision. | `renovation-design-brief` |
| [Renovation materials list](diy-home-renovations/renovation-materials-list.yaml) | Keeping every tool, material and finish for a renovation in one list — what to buy, from where, for how much, and whether it's arrived. | `renovation-materials-list` |
| [Renovation moodboard](diy-home-renovations/renovation-moodboard.yaml) | Collecting the look of a room you're about to renovate — photos, materials, colours, furniture and light — until the finished space is clear enough to build. | `renovation-moodboard` |
| [Renovation project plan](diy-home-renovations/renovation-project-plan.yaml) | Running a home renovation from first quote to final clean — the work in order, a board per room, the materials, the budget and the people doing it. | `renovation-project-plan` |

### Events

Plan an event's theme, logistics, schedule and guests.

| Template | Use it when | Slug |
|---|---|---|
| [Event brief](events/event-brief.yaml) | Briefing a production team on an event — what it's for, where it happens, what guests should experience and how it should look — before the run sheet gets written. | `event-brief` |
| [Event moodboard](events/event-moodboard.yaml) | Defining the look and atmosphere of an event — theme, colour, venue, props and the small details — so clients and suppliers can react before anything is booked. | `event-moodboard` |
| [Event planning](events/event-plan.yaml) | Planning an event from the first idea to the day after — objectives, dates, venue, suppliers, budget and the task list — in one place. | `event-plan` |
| [Event storyboard](events/event-storyboard.yaml) | Walking through an event in the order guests and crew will live it — bump-in to bump-out — so the moving parts and the gaps show up before the day. | `event-storyboard` |

### Education

Lesson plans, study notes and coursework.

| Template | Use it when | Slug |
|---|---|---|
| [Class notes](education/class-notes.yaml) | Keeping a course's notes organised — one board per lecture or seminar, with the readings, key dates and questions to revisit before the exam. | `class-notes` |
| [Research proposal](education/research-proposal.yaml) | Planning a research project before you ask for approval or funding — the question, the background, the method, the timeline and what you expect to find. | `research-proposal` |
| *[Academic project plan](project-plans/academic-plan.yaml)* | Planning an academic project or a course — the objectives, the method, the schedule around classes and the work broken into steps. | `academic-plan` |
| *[Brainstorming workshop](brainstorming/brainstorming-workshop.yaml)* | Running a brainstorm with a group — framing the question, getting ideas out fast, clustering them and leaving with a few to pursue. | `brainstorming-workshop` |

### Agencies

Client work end to end — pitches, briefs, presentations and handover.

| Template | Use it when | Slug |
|---|---|---|
| [Agency hub](agencies/agency-hub.yaml) | Running an agency from one board — strategy, every client project in its own board, new business, operations and the team, with the week's priorities on top. | `agency-hub` |
| *[Advertising brief](creative-briefs/advertising-brief.yaml)* | Briefing a creative team on an ad campaign — the business problem, the audience, and the one idea the work has to land. | `advertising-brief` |
| *[Marketing campaign moodboard](marketing-campaign/marketing-campaign-moodboard.yaml)* | Setting the look of a campaign before design starts — the colours, type, imagery and branding cues it should share, pinned up where everyone can see them. | `marketing-campaign-moodboard` |
| *[Team planner](productivity/team-planner.yaml)* | Managing a team's workload in one view — the priorities, who's on what with due dates, meeting notes and anything blocking the work. | `team-planner` |
| *[TVC advertising storyboard](storyboards/tvc-advertising-storyboard.yaml)* | Pitching or planning a TV or online commercial, frame by frame against the clock, so every second earns its place and the must-have shots are covered. | `tvc-advertising-storyboard` |

### Startups

Ideas, pitches, planning and the first customers.

| Template | Use it when | Slug |
|---|---|---|
| [AARRR metrics](startups/aarrr-metrics.yaml) | Checking a startup's health stage by stage — acquisition, activation, retention, referral, revenue — side by side, to decide which part of the funnel to work on next. | `aarrr-metrics` |
| [Lean canvas](startups/lean-canvas.yaml) | Getting a startup idea onto one page — the problem, the customer, the promise, the solution and how the money works — so the riskiest assumptions are in plain sight. | `lean-canvas` |
| [Startup hub](startups/startup-hub.yaml) | Running a young company from one board — strategy, product roadmap, growth, funding and team each in their own board, with this week's priorities on top. | `startup-hub` |
| [Value proposition canvas](startups/value-proposition-canvas.yaml) | Checking a product fits its customer — the jobs, pains and gains on one side, the features, pain relievers and gain creators on the other — and finding where they don't line up. | `value-proposition-canvas` |

<!-- index:end -->
