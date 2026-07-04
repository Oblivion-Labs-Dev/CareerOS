import React, { useState, useEffect } from 'react';
import { getProfile, saveProfile, enrichProfile } from './profileStore';
import { getDocuments, saveDocuments } from '../documents/documentStore';
import { UserProfile, FileAttachment, WorkExperienceEntry } from '../shared/types';
import { DEFAULT_SCREENING_ANSWERS, syncProfileFromScreeningAnswers } from '../shared/screeningAnswers';
import { APPLICATION_FIELD_DEFAULTS, PROFILE_FORM_OPTIONS } from '../shared/applicationDefaults';
import { parseLocationParts, preferredStateFillValue } from '../shared/usStates';
import { resolveMostRecentEmployer } from '../shared/workExperience';
import { syncFromServer, syncToServer } from '../db/sync';

function FieldHint({ children }: { children: React.ReactNode }) {
  return <p className="profile-field-hint">{children}</p>;
}

function ProfileSelect({
  id,
  value,
  options,
  onChange,
  allowCustom = true
}: {
  id: string;
  value: string;
  options: readonly string[];
  onChange: (e: React.ChangeEvent<HTMLSelectElement>) => void;
  allowCustom?: boolean;
}) {
  const uniqueOptions = [...new Set(options.filter(Boolean))];
  const hasValue = value.trim() && !uniqueOptions.includes(value);

  return (
    <select id={id} value={value} onChange={onChange}>
      {!value.trim() && <option value="">Select…</option>}
      {hasValue && allowCustom && (
        <option value={value}>{value}</option>
      )}
      {uniqueOptions.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}

export function ProfileCenter() {
  const [profile, setProfile] = useState<UserProfile>({
    firstName: '',
    lastName: '',
    fullName: '',
    email: '',
    phone: '',
    location: '',
    linkedin: '',
    github: '',
    portfolio: '',
    workAuthorization: 'Yes',
    sponsorship: 'Yes',
    yearsExperience: '',
    currentTitle: '',
    targetRole: '',
    salaryExpectations: '',
    currentCompany: '',
    pronouns: '',
    gender: '',
    raceEthnicity: '',
    hispanic: '',
    veteran: APPLICATION_FIELD_DEFAULTS.veteran,
    disability: APPLICATION_FIELD_DEFAULTS.disability,
    smsConsent: APPLICATION_FIELD_DEFAULTS.smsConsent,
    customFields: {},
    workExperience: [],
    screeningAnswers: DEFAULT_SCREENING_ANSWERS.map((entry) => ({ ...entry }))
  });

  const [status, setStatus] = useState('');
  const [statusType, setStatusType] = useState<'success' | 'error' | ''>('');
  const [resumeName, setResumeName] = useState('No file selected');
  const [coverLetterName, setCoverLetterName] = useState('No file selected');
  const [serverOnline, setServerOnline] = useState(true);

  useEffect(() => {
    loadProfileData();
  }, []);

  const loadProfileData = async () => {
    const synced = await syncFromServer();
    setServerOnline(synced);

    const data = await getProfile();
    if (data) {
      // Smart one-time cleanup of garbage custom fields
      const BLACKLISTED_KEYWORDS = [
        'search', 'textbox', 'select...', 'select', 'input', 'text', 'textarea',
        'dropdown', 'upload', 'drop or select', 'drag', 'pdf', 'docx', 'doc',
        'resume', 'cover letter', 'cv', 'file', 'attach', 'browse', 'choose file',
        'yes -', 'no -', 'i consent', 'i agree'
      ];
      if (data.customFields) {
        let cleaned = false;
        const cleanFields = { ...data.customFields };
        for (const key of Object.keys(cleanFields)) {
          const keyLower = key.toLowerCase();
          const isBlacklisted = BLACKLISTED_KEYWORDS.some((kw) => keyLower.includes(kw)) || key.trim().length < 3;
          if (isBlacklisted) {
            delete cleanFields[key];
            cleaned = true;
          }
        }
        if (cleaned) {
          data.customFields = cleanFields;
          await saveProfile(data);
          await syncToServer();
        }
      }

      setProfile(
        enrichProfile(
          syncProfileFromScreeningAnswers({
            ...data,
            workExperience: data.workExperience || [],
            screeningAnswers: data.screeningAnswers?.length
              ? data.screeningAnswers
              : DEFAULT_SCREENING_ANSWERS.map((entry) => ({ ...entry }))
          })
        )
      );
    }
    const docs = await getDocuments();
    if (docs.defaultResume) {
      setResumeName(docs.defaultResume.name);
    }
    if (docs.defaultCoverLetter) {
      setCoverLetterName(docs.defaultCoverLetter.name);
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { id, value } = e.target;
    setProfile(prev => ({
      ...prev,
      [id]: value
    }));
  };

  const handleFileUpload = async (
    file: File,
    type: 'resume' | 'coverLetter',
    setName: (name: string) => void
  ) => {
    const base64 = await readFileAsDataUrl(file);
    const attachment: FileAttachment = { name: file.name, type: file.type, base64 };
    const docs = await getDocuments();

    if (type === 'resume') {
      docs.defaultResume = attachment;
    } else {
      docs.defaultCoverLetter = attachment;
    }

    await saveDocuments(docs);
    await syncToServer();
    setName(file.name);
  };

  const readFileAsDataUrl = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });

  const updateWorkExperience = (
    index: number,
    field: keyof WorkExperienceEntry,
    value: string | boolean
  ) => {
    setProfile((prev) => {
      const list = [...(prev.workExperience || [])];
      list[index] = { ...list[index], [field]: value };
      return { ...prev, workExperience: list };
    });
  };

  const updateScreeningAnswer = (index: number, answer: string) => {
    setProfile((prev) => {
      const list = [...(prev.screeningAnswers || DEFAULT_SCREENING_ANSWERS.map((entry) => ({ ...entry })))];
      list[index] = { ...list[index], answer };
      return syncProfileFromScreeningAnswers({ ...prev, screeningAnswers: list });
    });
  };

  const updateCustomField = (key: string, value: string) => {
    setProfile((prev) => ({
      ...prev,
      customFields: { ...(prev.customFields || {}), [key]: value }
    }));
  };

  const { city: locationCity, state: locationState } = parseLocationParts(profile.location || '');
  const derivedEmployer = resolveMostRecentEmployer(profile);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus('Saving to server...');
    setStatusType('');
    
    try {
      await saveProfile(profile);
      const synced = await syncToServer();
      setServerOnline(synced);

      setStatusType(synced ? 'success' : 'error');
      setStatus(
        synced
          ? 'Profile updated and synchronized successfully!'
          : 'Profile saved locally, but server sync failed. Start server with: node server.js'
      );
      setTimeout(() => setStatus(''), 4000);
    } catch (err) {
      setStatusType('error');
      setStatus('Failed to save profile changes.');
    }
  };

  return (
    <div className="profile-page">
      <div className="dash-page-header">
        <h1>User Profile</h1>
        <p>Configure your master details to automatically map and populate application forms.</p>
        {!serverOnline && (
          <div className="alert-banner">
            Local server offline — you can still edit and save here. Run <code>node server.js</code> in the extension folder to sync to db.json.
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="form-grid" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <details className="review-card profile-section profile-field-map">
          <summary className="profile-field-map-summary">Autofill field map</summary>
          <p className="profile-file-hint">
            Every field below is saved to your profile and used when you run Autofill on job applications.
          </p>
          <ul className="profile-field-map-list">
            <li><strong>Personal</strong> — name, email, phone, location, address</li>
            <li><strong>Links</strong> — LinkedIn, GitHub, portfolio</li>
            <li><strong>Work status</strong> — authorization, sponsorship, title, employer, salary</li>
            <li><strong>Work experience</strong> — Workday employment history sections</li>
            <li><strong>Screening</strong> — Yes/No visa, relocation, and eligibility questions</li>
            <li><strong>Self-ID</strong> — pronouns, gender, race, veteran, disability, SMS consent</li>
            <li><strong>Documents</strong> — resume and cover letter uploads</li>
            <li><strong>Discovered</strong> — extra fields learned from past application scans</li>
          </ul>
        </details>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>👤</span> Personal details</h3>
          
          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="firstName">First Name</label>
              <FieldHint>Maps to first name, given name fields.</FieldHint>
              <input type="text" id="firstName" value={profile.firstName} onChange={handleInputChange} placeholder="Jane" />
            </div>
            <div className="form-group">
              <label htmlFor="lastName">Last Name</label>
              <FieldHint>Maps to last name, family name, surname fields.</FieldHint>
              <input type="text" id="lastName" value={profile.lastName} onChange={handleInputChange} placeholder="Doe" />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="fullName">Full Name</label>
            <FieldHint>Used when applications ask for a single full-name field.</FieldHint>
            <input type="text" id="fullName" value={profile.fullName} onChange={handleInputChange} placeholder="Jane Doe" />
          </div>

          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="email">Email address</label>
              <FieldHint>Primary contact email on application forms.</FieldHint>
              <input type="email" id="email" value={profile.email} onChange={handleInputChange} placeholder="jane.doe@example.com" />
            </div>
            <div className="form-group">
              <label htmlFor="phone">Phone Number</label>
              <FieldHint>Phone, mobile, and telephone fields.</FieldHint>
              <input type="tel" id="phone" value={profile.phone} onChange={handleInputChange} placeholder="+1 (555) 123-4567" />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="location">Location (City, State)</label>
            <FieldHint>
              Residence and work-location comboboxes (e.g. Snowflake). Seattle, WA types Seattle and selects
              &quot;Seattle, Washington, United States&quot;. City/state fields are derived from this value.
            </FieldHint>
            <input type="text" id="location" value={profile.location} onChange={handleInputChange} placeholder="Seattle, WA" />
            {(locationCity || locationState) && (
              <p className="profile-derived-values">
                Autofill will use city: <strong>{locationCity || '—'}</strong>
                {locationState && (
                  <> · state: <strong>{preferredStateFillValue(locationState)}</strong></>
                )}
              </p>
            )}
          </div>
        </div>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>🏠</span> Address</h3>
          <p className="profile-file-hint">
            Optional street and postal fields for applications that split address into separate inputs.
          </p>

          <div className="form-group">
            <label htmlFor="addressLine1">Street address</label>
            <FieldHint>Address line 1, street, and mailing address fields.</FieldHint>
            <input
              type="text"
              id="addressLine1"
              value={profile.customFields?.addressLine1 || profile.customFields?.street || ''}
              onChange={(e) => updateCustomField('addressLine1', e.target.value)}
              placeholder="123 Main St"
            />
          </div>

          <div className="form-group">
            <label htmlFor="zip">ZIP / postal code</label>
            <FieldHint>ZIP, postal code, and postcode fields.</FieldHint>
            <input
              type="text"
              id="zip"
              value={profile.customFields?.zip || profile.customFields?.postalCode || ''}
              onChange={(e) => {
                const postal = e.target.value;
                setProfile((prev) => ({
                  ...prev,
                  customFields: { ...(prev.customFields || {}), zip: postal, postalCode: postal }
                }));
              }}
              placeholder="98101"
            />
          </div>
        </div>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>🔗</span> Professional links</h3>
          
          <div className="form-group">
            <label htmlFor="linkedin">LinkedIn URL</label>
            <FieldHint>LinkedIn profile URL fields.</FieldHint>
            <input type="url" id="linkedin" value={profile.linkedin} onChange={handleInputChange} placeholder="https://linkedin.com/in/username" />
          </div>

          <div className="form-group">
            <label htmlFor="github">GitHub URL</label>
            <FieldHint>GitHub profile and repository links.</FieldHint>
            <input type="url" id="github" value={profile.github} onChange={handleInputChange} placeholder="https://github.com/username" />
          </div>

          <div className="form-group">
            <label htmlFor="portfolio">Portfolio URL</label>
            <FieldHint>Personal website, portfolio, and other URL fields.</FieldHint>
            <input type="url" id="portfolio" value={profile.portfolio} onChange={handleInputChange} placeholder="https://janedoe.dev" />
          </div>
        </div>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>💼</span> Work status & targets</h3>

          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="workAuthorization">Legally Authorized to Work?</label>
              <FieldHint>U.S. work authorization and eligibility questions.</FieldHint>
              <select id="workAuthorization" value={profile.workAuthorization} onChange={handleInputChange}>
                <option value="Yes">Yes</option>
                <option value="No">No</option>
              </select>
            </div>
            <div className="form-group">
              <label htmlFor="sponsorship">Will Require Visa Sponsorship?</label>
              <FieldHint>Visa sponsorship now or in the future.</FieldHint>
              <select id="sponsorship" value={profile.sponsorship} onChange={handleInputChange}>
                <option value="No">No</option>
                <option value="Yes">Yes</option>
              </select>
            </div>
          </div>

          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="yearsExperience">Years of experience</label>
              <FieldHint>Years of professional experience dropdowns.</FieldHint>
              <input type="number" id="yearsExperience" min="0" value={profile.yearsExperience} onChange={handleInputChange} placeholder="5" />
            </div>
            <div className="form-group">
              <label htmlFor="salaryExpectations">Target Salary Expectation</label>
              <FieldHint>Salary, compensation, and pay expectation fields.</FieldHint>
              <input type="text" id="salaryExpectations" value={profile.salaryExpectations} onChange={handleInputChange} placeholder="$140,000 - $160,000" />
            </div>
          </div>

          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="currentTitle">Current job title</label>
              <FieldHint>Current role and job title fields.</FieldHint>
              <input type="text" id="currentTitle" value={profile.currentTitle} onChange={handleInputChange} placeholder="Software Engineer" />
            </div>
            <div className="form-group">
              <label htmlFor="targetRole">Target Job Title</label>
              <FieldHint>Desired role or position you are applying for.</FieldHint>
              <input type="text" id="targetRole" value={profile.targetRole} onChange={handleInputChange} placeholder="Senior Software Engineer" />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="currentCompany">Most recent employer</label>
            <FieldHint>
              &quot;Where have you most recently worked?&quot;, current company, and employer name fields.
              {derivedEmployer && derivedEmployer !== profile.currentCompany?.trim() && (
                <> Autofill fallback from work history: <strong>{derivedEmployer}</strong>.</>
              )}
            </FieldHint>
            <input
              type="text"
              id="currentCompany"
              value={profile.currentCompany || ''}
              onChange={handleInputChange}
              placeholder="Microsoft"
            />
          </div>
        </div>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>🧾</span> Work experience</h3>
          <p className="profile-file-hint">
            Saved roles for Workday-style applications. Role descriptions are pulled from your resume when you upload or sync.
          </p>

          {(profile.workExperience || []).map((entry, index) => (
            <div key={`${entry.company}-${index}`} className="work-exp-card">
              <h4 className="work-exp-title">
                {entry.jobTitle || 'Role'} at {entry.company || 'Company'}
              </h4>

              <div className="profile-grid-2">
                <div className="form-group">
                  <label>Job title</label>
                  <input
                    type="text"
                    value={entry.jobTitle}
                    onChange={(e) => updateWorkExperience(index, 'jobTitle', e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label>Company</label>
                  <input
                    type="text"
                    value={entry.company}
                    onChange={(e) => updateWorkExperience(index, 'company', e.target.value)}
                  />
                </div>
              </div>

              <div className="profile-grid-2">
                <div className="form-group">
                  <label>Location</label>
                  <input
                    type="text"
                    value={entry.location}
                    onChange={(e) => updateWorkExperience(index, 'location', e.target.value)}
                  />
                </div>
                <div className="form-group">
                  <label className="work-exp-checkbox">
                    <input
                      type="checkbox"
                      checked={entry.currentlyEmployed}
                      onChange={(e) => updateWorkExperience(index, 'currentlyEmployed', e.target.checked)}
                    />
                    I currently work here
                  </label>
                </div>
              </div>

              <div className="profile-grid-2">
                <div className="form-group">
                  <label>From (MM/YYYY)</label>
                  <input
                    type="text"
                    value={entry.startDate}
                    onChange={(e) => updateWorkExperience(index, 'startDate', e.target.value)}
                    placeholder="08/2019"
                  />
                </div>
                <div className="form-group">
                  <label>To (MM/YYYY)</label>
                  <input
                    type="text"
                    value={entry.endDate || ''}
                    onChange={(e) => updateWorkExperience(index, 'endDate', e.target.value)}
                    placeholder="08/2025"
                    disabled={entry.currentlyEmployed}
                  />
                </div>
              </div>

              <div className="form-group">
                <label>Role description</label>
                <textarea
                  rows={5}
                  value={entry.description}
                  onChange={(e) => updateWorkExperience(index, 'description', e.target.value)}
                  placeholder="Bullets and technologies — auto-filled from resume on sync"
                />
              </div>
            </div>
          ))}
        </div>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>✅</span> Screening questions (Yes / No)</h3>
          <p className="profile-file-hint">
            Saved answers for visa, relocation, and eligibility dropdowns on applications like Snap Workday.
          </p>

          {(profile.screeningAnswers || DEFAULT_SCREENING_ANSWERS).map((entry, index) => (
            <div key={entry.id} className="screening-answer-card">
              <label className="screening-question">{entry.question}</label>
              <select
                className="screening-answer-select"
                value={entry.answer}
                onChange={(e) => updateScreeningAnswer(index, e.target.value)}
              >
                <option value="Yes">Yes</option>
                <option value="No">No</option>
              </select>
            </div>
          ))}
        </div>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>🪪</span> Voluntary self-identification</h3>
          <p className="profile-file-hint">
            Pronouns, EEO, veteran status, disability, and SMS consent dropdowns on job applications.
          </p>

          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="pronouns">Pronouns</label>
              <FieldHint>He/him, she/her, they/them, and similar fields.</FieldHint>
              <input
                type="text"
                id="pronouns"
                value={profile.pronouns || ''}
                onChange={handleInputChange}
                placeholder="He/him/his"
              />
            </div>
            <div className="form-group">
              <label htmlFor="gender">Gender</label>
              <FieldHint>Gender and sex self-identification dropdowns.</FieldHint>
              <ProfileSelect
                id="gender"
                value={profile.gender || ''}
                options={PROFILE_FORM_OPTIONS.gender}
                onChange={handleInputChange}
              />
            </div>
          </div>

          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="raceEthnicity">Race / ethnicity</label>
              <FieldHint>Race and ethnicity EEO questions.</FieldHint>
              <ProfileSelect
                id="raceEthnicity"
                value={profile.raceEthnicity || ''}
                options={PROFILE_FORM_OPTIONS.raceEthnicity}
                onChange={handleInputChange}
              />
            </div>
            <div className="form-group">
              <label htmlFor="hispanic">Hispanic / Latino</label>
              <FieldHint>Hispanic or Latino origin questions.</FieldHint>
              <ProfileSelect
                id="hispanic"
                value={profile.hispanic || ''}
                options={PROFILE_FORM_OPTIONS.hispanic}
                onChange={handleInputChange}
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="veteran">Veteran status</label>
            <FieldHint>Protected veteran and military service questions.</FieldHint>
            <ProfileSelect
              id="veteran"
              value={profile.veteran || APPLICATION_FIELD_DEFAULTS.veteran}
              options={PROFILE_FORM_OPTIONS.veteran}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group">
            <label htmlFor="disability">Disability status</label>
            <FieldHint>Disability self-identification (Section 503 / OFCCP).</FieldHint>
            <ProfileSelect
              id="disability"
              value={profile.disability || APPLICATION_FIELD_DEFAULTS.disability}
              options={PROFILE_FORM_OPTIONS.disability}
              onChange={handleInputChange}
            />
          </div>

          <div className="form-group">
            <label htmlFor="smsConsent">SMS / text message consent</label>
            <FieldHint>Consent to receive recruiting text messages.</FieldHint>
            <ProfileSelect
              id="smsConsent"
              value={profile.smsConsent || APPLICATION_FIELD_DEFAULTS.smsConsent}
              options={PROFILE_FORM_OPTIONS.smsConsent}
              onChange={handleInputChange}
            />
          </div>
        </div>

        <div className="review-card profile-section">
          <h3 className="profile-section-title"><span>📄</span> Application documents</h3>
          <p className="profile-file-hint">
            Upload your default resume and cover letter for Greenhouse file inputs.
          </p>

          <div className="profile-grid-2">
            <div className="form-group">
              <label htmlFor="profile-resume">Default resume</label>
              <input
                type="file"
                id="profile-resume"
                className="profile-file-input"
                accept=".pdf,.doc,.docx"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file, 'resume', setResumeName);
                }}
              />
              <span className="profile-file-hint">{resumeName}</span>
            </div>
            <div className="form-group">
              <label htmlFor="profile-cover-letter">Default cover letter</label>
              <input
                type="file"
                id="profile-cover-letter"
                className="profile-file-input"
                accept=".pdf,.doc,.docx"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFileUpload(file, 'coverLetter', setCoverLetterName);
                }}
              />
              <span className="profile-file-hint">{coverLetterName}</span>
            </div>
          </div>
        </div>

        {profile.customFields && Object.keys(profile.customFields).length > 0 && (
          <div className="review-card profile-section">
            <h3 className="profile-section-title"><span>🧩</span> Custom & Discovered Fields</h3>
            <p className="profile-file-hint">
              These fields were automatically discovered from your job application scans. Provide answers here to automatically fill them in next time.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {Object.keys(profile.customFields).map((label) => (
                <div className="form-group" key={label}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <label htmlFor={`custom-${label}`} style={{ margin: 0, fontWeight: 500 }}>{label}</label>
                    <button
                      type="button"
                      className="btn"
                      style={{ padding: '2px 8px', fontSize: '0.7rem', height: 'auto', background: 'rgba(239, 68, 68, 0.1)', color: '#f87171', border: '1px solid rgba(239, 68, 68, 0.2)' }}
                      onClick={() => {
                        const updatedFields = { ...profile.customFields };
                        delete updatedFields[label];
                        setProfile(prev => ({
                          ...prev,
                          customFields: updatedFields
                        }));
                      }}
                    >
                      Delete
                    </button>
                  </div>
                  <input
                    type="text"
                    id={`custom-${label}`}
                    value={profile.customFields![label]}
                    onChange={(e) => {
                      const val = e.target.value;
                      setProfile(prev => ({
                        ...prev,
                        customFields: {
                          ...prev.customFields,
                          [label]: val
                        }
                      }));
                    }}
                    placeholder="Enter answer..."
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="profile-actions">
          <button type="submit" className="btn btn-success btn-lg" style={{ width: 'fit-content' }}>
            Save profile settings
          </button>
          
          {status && (
            <span className={`profile-status ${statusType}`}>
              {status}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}
