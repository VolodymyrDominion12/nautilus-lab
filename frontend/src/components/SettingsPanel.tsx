import React, { useEffect, useState } from 'react';
import { ShieldAlert } from 'lucide-react';
import {
  fetchSettings,
  fetchSettingsSchema,
  saveSettings,
} from '../services/api';
import type { SettingGroup } from '../services/api';

export const SettingsPanel: React.FC = () => {
  const [settings, setSettings] = useState<Record<string, string>>({});
  const [groups, setGroups] = useState<SettingGroup[]>([]);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [expandedGroup, setExpandedGroup] = useState<string>('risk');

  useEffect(() => {
    Promise.all([fetchSettings(), fetchSettingsSchema()])
      .then(([settingsRes, schemaRes]) => {
        setSettings(settingsRes.settings || {});
        setGroups(schemaRes.groups || []);
      })
      .catch((err) => console.error(err));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setMessage('');
    try {
      await saveSettings(settings);
      setMessage('Settings saved successfully.');
      const refreshed = await fetchSettings();
      setSettings(refreshed.settings || {});
    } catch (err: any) {
      setMessage(err.message || 'Error saving settings.');
    }
    setSaving(false);
  };

  const handleChange = (key: string, value: string) => {
    setSettings((prev) => ({ ...prev, [key]: value }));
  };

  const renderField = (field: SettingGroup['fields'][number]) => {
    const value = settings[field.key] ?? '';

    if (field.field_type === 'boolean') {
      const checked = value.toLowerCase() === 'true';
      return (
        <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-300">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => handleChange(field.key, e.target.checked ? 'true' : 'false')}
            className="rounded bg-gray-950 border-gray-700 text-blue-600 focus:ring-0"
          />
          {field.label}
        </label>
      );
    }

    if (field.field_type === 'select' && field.options) {
      return (
        <select
          value={value}
          onChange={(e) => handleChange(field.key, e.target.value)}
          className="bg-gray-950 border border-gray-800 text-gray-100 text-xs rounded-xl p-2.5 focus:border-blue-500 focus:outline-none font-mono w-full"
        >
          {field.options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      );
    }

    return (
      <input
        type={field.field_type === 'secret' ? 'password' : field.field_type === 'number' ? 'number' : 'text'}
        value={value}
        onChange={(e) => handleChange(field.key, e.target.value)}
        placeholder={field.field_type === 'secret' ? 'Leave blank to keep current value' : ''}
        className="bg-gray-950 border border-gray-800 text-gray-100 text-xs rounded-xl focus:border-blue-500 focus:outline-none p-2.5 font-mono w-full"
      />
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="bg-gray-900 rounded-2xl border border-gray-800 p-6 flex flex-col gap-4">
        <div className="flex justify-between items-center gap-4 flex-wrap">
          <div>
            <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-amber-400" />
              Environment Configuration
            </h2>
            <p className="text-gray-400 text-xs mt-1">
              Grouped .env settings with validation. Secrets are masked on load; leave blank to keep them.
            </p>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:bg-gray-700 text-white rounded-xl text-sm font-medium transition-colors"
          >
            {saving ? 'Saving...' : 'Save Settings'}
          </button>
        </div>

        {message && (
          <div
            className={`p-3 rounded-xl border text-xs ${
              message.includes('success')
                ? 'bg-emerald-950/40 text-emerald-400 border-emerald-800/50'
                : 'bg-red-950/40 text-red-400 border-red-800/50'
            }`}
          >
            {message}
          </div>
        )}

        <div className="flex flex-col gap-3 mt-2">
          {groups.map((group) => (
            <div key={group.id} className="border border-gray-800 rounded-2xl overflow-hidden">
              <button
                type="button"
                onClick={() => setExpandedGroup(expandedGroup === group.id ? '' : group.id)}
                className="w-full px-4 py-3 bg-gray-950/70 flex justify-between items-center text-left hover:bg-gray-950"
              >
                <div>
                  <div className="text-sm font-semibold text-gray-100">{group.title}</div>
                  <div className="text-[11px] text-gray-500 mt-0.5">{group.description}</div>
                </div>
                <span className="text-xs text-gray-500">{expandedGroup === group.id ? '−' : '+'}</span>
              </button>

              {expandedGroup === group.id && (
                <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-4 border-t border-gray-800/80">
                  {group.fields.map((field) => (
                    <div key={field.key} className="flex flex-col gap-1.5">
                      {field.field_type !== 'boolean' && (
                        <label className="text-[11px] font-mono text-gray-400">{field.key}</label>
                      )}
                      {renderField(field)}
                      {field.description && field.field_type !== 'boolean' && (
                        <span className="text-[10px] text-gray-600">{field.description}</span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
